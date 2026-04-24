# marneo/memory/core.py
"""Core Memory — always-loaded critical constraints.

Stored as ~/.marneo/employees/<name>/memory/core.md
Write paths: manual CLI, LLM tool, episode promotion.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MAX_CHARS = 1000


class CoreMemory:
    """Read/write core.md for one employee."""

    def __init__(self, path: Path, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        self._path = path
        self._max_chars = max_chars

    def _load(self) -> tuple[dict, list[dict]]:
        """Return (meta, entries). Entries: [{"content": str, "source": str}]"""
        if not self._path.exists():
            return {}, []
        text = self._path.read_text(encoding="utf-8").strip()
        meta: dict[str, Any] = {}
        body = text
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                try:
                    meta = yaml.safe_load(text[3:end]) or {}
                except Exception:
                    pass
                body = text[end + 3:].strip()
        entries = []
        for line in body.splitlines():
            m = re.match(r"^[-*]\s+(.+?)(?:\s+\[(.+?)\])?$", line.strip())
            if m:
                entries.append({"content": m.group(1).strip(), "source": m.group(2) or "manual"})
        return meta, entries

    def _save(self, entries: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        meta = {"updated_at": str(date.today())}
        lines = [f"---\n{yaml.dump(meta, allow_unicode=True)}---\n\n# 核心记忆\n"]
        for e in entries:
            lines.append(f"- {e['content']} [{e['source']}]")
        self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @property
    def content(self) -> str:
        _, entries = self._load()
        return "\n".join(e["content"] for e in entries)

    def list_entries(self) -> list[dict]:
        _, entries = self._load()
        return entries

    def add(self, content: str, source: str = "manual") -> None:
        _, entries = self._load()
        if any(e["content"] == content for e in entries):
            return
        entries.append({"content": content, "source": source})
        self._save(entries)

    def remove(self, content: str) -> bool:
        _, entries = self._load()
        new_entries = [e for e in entries if e["content"] != content]
        if len(new_entries) == len(entries):
            return False
        self._save(new_entries)
        return True

    def as_prompt(self) -> str:
        """Return formatted string for injection into system prompt."""
        _, entries = self._load()
        if not entries:
            return ""
        lines = ["# 核心记忆（关键约束，必须遵守）"]
        for e in entries:
            lines.append(f"- {e['content']}")
        text = "\n".join(lines)
        if len(text) > self._max_chars:
            text = text[:self._max_chars - 20] + "\n...(已截断)"
        return text

    @classmethod
    def for_employee(cls, employee_name: str, max_chars: int = DEFAULT_MAX_CHARS) -> "CoreMemory":
        from marneo.core.paths import get_marneo_dir
        path = get_marneo_dir() / "employees" / employee_name / "memory" / "core.md"
        return cls(path, max_chars)
