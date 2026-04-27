# marneo/memory/session_memory.py
"""SessionMemory — per-session context builder with budget enforcement."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class ContextBudget:
    system_prompt_max: int = 4000
    core_memory_max: int = 1000
    working_memory_turns: int = 20
    episodic_inject_max: int = 1500
    tool_result_max: int = 50_000

    @classmethod
    def from_config(cls) -> "ContextBudget":
        try:
            from marneo.core.config import load_config
            cfg = load_config()
            raw = getattr(cfg, "context_budget", None)
            if not raw:
                return cls()
            if isinstance(raw, dict):
                return cls(
                    system_prompt_max=int(raw.get("system_prompt_max", 4000)),
                    core_memory_max=int(raw.get("core_memory_max", 1000)),
                    working_memory_turns=int(raw.get("working_memory_turns", 20)),
                    episodic_inject_max=int(raw.get("episodic_inject_max", 1500)),
                    tool_result_max=int(raw.get("tool_result_max", 50_000)),
                )
        except Exception as exc:
            log.warning("[SessionMemory] config loading failed: %s", exc)
        return cls()


class SessionMemory:
    def __init__(self, employee_name: str, soul: str = "", budget: Optional[ContextBudget] = None) -> None:
        self._employee_name = employee_name
        self._soul = soul
        self._budget = budget or ContextBudget.from_config()
        self._core: Any = None
        self._retriever: Any = None
        self._store: Any = None

    def _get_core(self) -> Any:
        if self._core is None:
            from marneo.memory.core import CoreMemory
            self._core = CoreMemory.for_employee(self._employee_name, self._budget.core_memory_max)
        return self._core

    def _get_retriever(self) -> Any:
        if self._retriever is None:
            try:
                from marneo.memory.retriever import HybridRetriever
                from marneo.memory.skill_index import index_skills_into_store
                from marneo.core.paths import get_marneo_dir

                retriever = HybridRetriever.for_employee(self._employee_name)
                store = retriever._store
                index_skills_into_store(get_marneo_dir() / "skills", store)
                retriever.rebuild_index()
                self._retriever = retriever
                self._store = store
            except Exception as e:
                log.warning("[SessionMemory] Retriever init failed: %s", e)
        return self._retriever

    def build_system_prompt(self, query: str = "", skip_retrieval: bool = False) -> str:
        """Build fixed system prompt: capability directive + SOUL + Core Memory."""
        parts: list[str] = []

        # Always prepend the capability directive so LLM knows to use tools
        capability_directive = (
            "You are a work-focused digital employee running inside Marneo. "
            "You are capable, direct, and action-oriented. "
            "When asked to do something, use your tools to actually do it — "
            "do NOT say you cannot, and do NOT describe what you would do. "
            "Prefer tool evidence over recall. Be concise. Report results, not intentions."
        )
        parts.append(capability_directive)

        soul = self._soul.strip()
        if soul:
            max_soul = self._budget.system_prompt_max - self._budget.core_memory_max - 100
            if len(soul) > max_soul and max_soul > 0:
                soul = soul[:max_soul]
            parts.append(soul)

        core_prompt = self._get_core().as_prompt()
        if core_prompt:
            parts.append(core_prompt)

        result = "\n\n".join(parts)
        if len(result) > self._budget.system_prompt_max:
            result = result[:self._budget.system_prompt_max - 20] + "\n...(截断)"
        return result

    def retrieve_for_turn(self, query: str) -> str:
        """Retrieve relevant memories for current turn."""
        retriever = self._get_retriever()
        if retriever is None or not query.strip():
            return ""
        try:
            results = retriever.retrieve(query, n=3)
            if not results:
                return ""
            lines = ["# 相关经验（本轮参考）"]
            total = len(lines[0])
            for ep in results:
                line = f"- {ep.content}"
                if total + len(line) > self._budget.episodic_inject_max:
                    break
                lines.append(line)
                total += len(line)
            return "\n".join(lines) if len(lines) > 1 else ""
        except Exception as e:
            log.debug("[SessionMemory] retrieve_for_turn error: %s", e)
            return ""

    def trim_working_memory(self, messages: list[dict]) -> list[dict]:
        """Trim messages to last N turns (each turn = one user + one assistant message)."""
        max_turns = self._budget.working_memory_turns
        turn_count = 0
        i = len(messages)
        while i > 0 and turn_count < max_turns:
            i -= 1
            if messages[i].get("role") == "assistant":
                turn_count += 1
                # include the paired user message that precedes this assistant
                if i > 0 and messages[i - 1].get("role") == "user":
                    i -= 1
        return messages[i:]

    def add_episode_from_turn(self, user_msg: str, assistant_reply: str) -> None:
        """Extract and save episode from conversation turn."""
        if self._store is None:
            self._get_retriever()
        if self._store is None:
            return
        try:
            from marneo.memory.extractor import extract_episode
            ep = extract_episode(user_msg, assistant_reply)
            if ep:
                self._store.add(ep)
        except Exception as e:
            log.debug("[SessionMemory] Episode extraction error: %s", e)

    def check_and_promote(self, min_access: int = 5) -> int:
        """Score and promote high-value episodes to core memory.

        Scoring formula (openclaw short-term-promotion pattern):
          relevance  30%  — importance field (set by extractor heuristic)
          frequency  24%  — access_count normalized to 0-1
          freshness  15%  — days since creation (decay: 1 / (1 + days/30))
          diversity  15%  — type rarity bonus (less common types score higher)
          size       10%  — shorter episodes preferred (1 / (1 + chars/200))
          promoted    6%  — penalty if already promoted (always 1.0 here)
        """
        import time as _time

        if self._store is None:
            return 0
        candidates = self._store.get_promotion_candidates(min_access=min_access)
        if not candidates:
            return 0

        # Type frequency for diversity scoring
        all_eps = self._store.get_all()
        type_counts: dict[str, int] = {}
        for ep in all_eps:
            type_counts[ep.type] = type_counts.get(ep.type, 0) + 1
        total_eps = max(len(all_eps), 1)
        max_access = max((ep.access_count for ep in candidates), default=1) or 1

        core = self._get_core()
        promoted = 0
        now = _time.time()

        scored: list[tuple[float, Any]] = []
        for ep in candidates:
            # Parse created_at
            try:
                from datetime import datetime
                dt = datetime.strptime(ep.created_at[:10], "%Y-%m-%d")
                days_old = (now - dt.timestamp()) / 86400
            except Exception:
                days_old = 30

            relevance = ep.importance                                  # 0-1
            frequency = ep.access_count / max_access                   # 0-1
            freshness = 1.0 / (1.0 + days_old / 30)                   # decay curve
            type_freq = type_counts.get(ep.type, 1) / total_eps
            diversity = 1.0 - type_freq                                # rare types score higher
            size = 1.0 / (1.0 + len(ep.content) / 200)                # shorter preferred

            score = (
                0.30 * relevance
                + 0.24 * frequency
                + 0.15 * freshness
                + 0.15 * diversity
                + 0.10 * size
                + 0.06 * 1.0  # not-yet-promoted = full bonus
            )
            scored.append((score, ep))

        # Promote top scorers that fit in core budget
        scored.sort(key=lambda x: x[0], reverse=True)
        for score, ep in scored:
            if score < 0.3:
                break  # below threshold
            if len(core.content) + len(ep.content) < self._budget.core_memory_max:
                core.add(ep.content, source="promoted")
                self._store.mark_promoted(ep.id)
                promoted += 1
                log.info("[Memory] Promoted episode %s (score=%.2f): %s",
                         ep.id, score, ep.content[:60])

        return promoted

    def get_memory_tools(self) -> tuple[list[dict], dict]:
        """Return (tool_schemas, tool_handlers) for injection into ChatSession."""
        from marneo.tools.core.memory_tools import (
            MEMORY_TOOL_SCHEMAS, recall_memory, get_skill,
            add_core_memory, add_episode,
        )
        retriever = self._get_retriever()
        core = self._get_core()
        store = self._store
        handlers = {
            "recall_memory": lambda args, **kw: recall_memory(args, _retriever=retriever, **kw),
            "get_skill": lambda args, **kw: get_skill(args, **kw),
            "add_core_memory": lambda args, **kw: add_core_memory(args, _core_memory=core, **kw),
            "add_episode": lambda args, **kw: add_episode(args, _store=store, **kw),
        }
        return MEMORY_TOOL_SCHEMAS, handlers
