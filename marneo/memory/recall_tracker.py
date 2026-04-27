# marneo/memory/recall_tracker.py
"""Recall tracker -- records memory retrieval hits for dreaming promotion.

Openclaw pattern: every memory_search hit is recorded with counts, scores,
query hashes, and timestamps. The dreaming sweep uses this data to decide
what gets promoted to long-term memory.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class RecallEntry:
    """A single tracked memory retrieval record."""

    key: str                                            # episode ID
    content: str                                        # snippet text
    recall_count: int = 0                               # organic search hits
    total_score: float = 0.0                            # sum of retrieval scores
    max_score: float = 0.0                              # best single score
    first_recalled_at: str = ""                         # ISO timestamp
    last_recalled_at: str = ""                          # ISO timestamp
    query_hashes: list[str] = field(default_factory=list)   # SHA-256 of distinct queries
    recall_days: list[str] = field(default_factory=list)    # distinct YYYY-MM-DD
    concept_tags: list[str] = field(default_factory=list)   # extracted concepts (max 8)
    promoted_at: str = ""                               # set after promotion


class RecallTracker:
    """Tracks memory retrieval hits for dreaming promotion decisions.

    Storage: JSON file at ~/.marneo/employees/{name}/memory/.dreams/recall.json
    Thread-safety: writes use atomic rename (write to tmp then os.replace).
    """

    def __init__(self, employee_name: str) -> None:
        self._employee_name = employee_name
        self._path = self._resolve_path(employee_name)
        self._entries: dict[str, RecallEntry] = {}
        self._dirty = False
        self._load()

    @staticmethod
    def _resolve_path(employee_name: str) -> Path:
        from marneo.core.paths import get_marneo_dir
        return (
            get_marneo_dir()
            / "employees"
            / employee_name
            / "memory"
            / ".dreams"
            / "recall.json"
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load recall entries from disk."""
        if not self._path.exists():
            self._entries = {}
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._entries = {
                key: RecallEntry(**val)
                for key, val in raw.items()
            }
        except Exception as exc:
            log.warning("[RecallTracker] Failed to load %s: %s", self._path, exc)
            self._entries = {}

    def _save(self) -> None:
        """Atomic write: tmp file then os.replace."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {key: asdict(entry) for key, entry in self._entries.items()}
        # Write to a temp file in the same directory for atomic rename
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._path.parent), suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            # Clean up tmp on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, episode_id: str, content: str, score: float, query: str) -> None:
        """Record a retrieval hit. Called from HybridRetriever.retrieve()."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        today = now.strftime("%Y-%m-%d")
        q_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()

        entry = self._entries.get(episode_id)
        if entry is None:
            entry = RecallEntry(
                key=episode_id,
                content=content[:500],
                recall_count=0,
                first_recalled_at=now_iso,
                concept_tags=self._extract_concepts(content),
            )
            self._entries[episode_id] = entry

        entry.recall_count += 1
        entry.total_score += score
        entry.max_score = max(entry.max_score, score)
        entry.last_recalled_at = now_iso

        if q_hash not in entry.query_hashes:
            entry.query_hashes.append(q_hash)
        if today not in entry.recall_days:
            entry.recall_days.append(today)

        self._dirty = True
        self._save()

    def get_candidates(self) -> list[RecallEntry]:
        """Return entries not yet promoted, sorted by recall_count desc."""
        candidates = [
            entry for entry in self._entries.values()
            if not entry.promoted_at
        ]
        candidates.sort(key=lambda e: e.recall_count, reverse=True)
        return candidates

    def mark_promoted(self, key: str) -> None:
        """Mark entry as promoted (exclude from future dreaming cycles)."""
        entry = self._entries.get(key)
        if entry is None:
            return
        entry.promoted_at = datetime.now(timezone.utc).isoformat()
        self._save()

    def get_entry(self, key: str) -> Optional[RecallEntry]:
        """Return a single entry by key, or None."""
        return self._entries.get(key)

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Concept extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_concepts(text: str) -> list[str]:
        """Extract concept tags from text (max 8). Simple keyword extraction.

        Uses a lightweight heuristic: split on non-alphanum boundaries,
        keep tokens that look like meaningful concepts (length >= 3,
        not pure stopwords), deduplicate, and cap at 8.
        """
        import re

        _STOPWORDS = frozenset({
            "the", "and", "for", "that", "this", "with", "from", "are",
            "was", "were", "been", "have", "has", "had", "not", "but",
            "they", "them", "than", "when", "will", "can", "may",
            "all", "each", "any", "some", "into", "also", "its",
            "you", "your", "our", "out", "about", "just", "very",
            # Chinese stopwords
            "\u7684", "\u4e86", "\u662f", "\u5728", "\u4e0d", "\u548c",
            "\u6709", "\u4eba", "\u8fd9", "\u4e2d",
        })

        # Split on whitespace and punctuation, keep CJK chars as individual tokens
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z][a-zA-Z0-9_\-]{2,}", text.lower())
        seen: set[str] = set()
        concepts: list[str] = []
        for tok in tokens:
            if tok in _STOPWORDS or tok in seen:
                continue
            seen.add(tok)
            concepts.append(tok)
            if len(concepts) >= 8:
                break
        return concepts

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def for_employee(cls, employee_name: str) -> "RecallTracker":
        return cls(employee_name)
