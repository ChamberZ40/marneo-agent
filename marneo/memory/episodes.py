# marneo/memory/episodes.py
"""Episodic Memory store — SQLite backend for work experience and skill index."""
from __future__ import annotations

import itertools
import json
import sqlite3
import time

_id_counter = itertools.count()
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Episode:
    content: str
    type: str = "general"         # decision/preference/discovery/problem/advice/general/skill
    source: str = "episode"       # "episode" | "skill"
    skill_id: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    project: str = ""
    importance: float = 0.5
    access_count: int = 0
    promoted_to_core: bool = False
    created_at: str = ""
    id: str = ""


class EpisodeStore:
    """Manages episodic memories in SQLite."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS episodes (
        id TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        type TEXT DEFAULT 'general',
        source TEXT DEFAULT 'episode',
        skill_id TEXT,
        tags TEXT DEFAULT '[]',
        project TEXT DEFAULT '',
        importance REAL DEFAULT 0.5,
        access_count INTEGER DEFAULT 0,
        promoted_to_core INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_source ON episodes(source);
    CREATE INDEX IF NOT EXISTS idx_access ON episodes(access_count);
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(self._SCHEMA)

    def _row_to_episode(self, row: sqlite3.Row) -> Episode:
        return Episode(
            id=row["id"],
            content=row["content"],
            type=row["type"],
            source=row["source"],
            skill_id=row["skill_id"],
            tags=json.loads(row["tags"] or "[]"),
            project=row["project"] or "",
            importance=row["importance"],
            access_count=row["access_count"],
            promoted_to_core=bool(row["promoted_to_core"]),
            created_at=row["created_at"],
        )

    def add(self, ep: Episode) -> str:
        ep_id = ep.id or f"ep_{int(time.time() * 1000)}_{next(_id_counter)}"
        created = ep.created_at or time.strftime("%Y-%m-%d")
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO episodes
                   (id, content, type, source, skill_id, tags, project,
                    importance, access_count, promoted_to_core, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (ep_id, ep.content, ep.type, ep.source, ep.skill_id,
                 json.dumps(ep.tags, ensure_ascii=False), ep.project,
                 ep.importance, ep.access_count, int(ep.promoted_to_core), created),
            )
        return ep_id

    def get(self, ep_id: str) -> Optional[Episode]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM episodes WHERE id=?", (ep_id,)).fetchone()
        return self._row_to_episode(row) if row else None

    def list_recent(self, limit: int = 20, source: Optional[str] = None) -> list[Episode]:
        sql = "SELECT * FROM episodes"
        params: list = []
        if source:
            sql += " WHERE source=?"
            params.append(source)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_episode(r) for r in rows]

    def get_all(self) -> list[Episode]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM episodes").fetchall()
        return [self._row_to_episode(r) for r in rows]

    def increment_access(self, ep_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE episodes SET access_count = access_count + 1 WHERE id=?",
                (ep_id,),
            )

    def get_promotion_candidates(self, min_access: int = 5) -> list[Episode]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE access_count >= ? AND promoted_to_core = 0",
                (min_access,),
            ).fetchall()
        return [self._row_to_episode(r) for r in rows]

    def mark_promoted(self, ep_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE episodes SET promoted_to_core=1 WHERE id=?",
                (ep_id,),
            )

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]

    @classmethod
    def for_employee(cls, employee_name: str) -> "EpisodeStore":
        from marneo.core.paths import get_marneo_dir
        db_path = (
            get_marneo_dir()
            / "employees"
            / employee_name
            / "memory"
            / "episodes"
            / "index.db"
        )
        return cls(db_path)
