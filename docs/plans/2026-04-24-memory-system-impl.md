# Memory System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Implement marneo's 3-tier memory system (Core / Episodic / Working) with BM25+fastembed hybrid retrieval, fixing the unbounded system prompt growth problem.

**Architecture:** Core Memory (always loaded, ≤1000 chars) stored in `core.md`. Episodic Memory (skills + work experience) indexed in SQLite with fastembed vectors + BM25. System prompt is rebuilt each turn from SOUL + Core + retrieved episodes (≤4500 chars total). Working memory capped at configurable turn limit.

**Tech Stack:** Python 3.11+, fastembed (local ~50MB model, no GPU), rank-bm25, SQLite (stdlib), existing ChatSession/registry.

**Reference:** Design doc at `docs/plans/2026-04-24-memory-system-design.md`. mempalace at `/Users/chamber/code/mempalace` (BM25+vector hybrid pattern).

---

## Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

### Step 1: Add to dependencies

```toml
dependencies = [
    ...existing deps...,
    "fastembed>=0.4.0",
    "rank-bm25>=0.2.2",
    "numpy>=1.24.0",
]
```

### Step 2: Install and verify

```bash
cd /Users/chamber/code/marneo-agent
pip install -e ".[dev]"
python3 -c "from fastembed import TextEmbedding; from rank_bm25 import BM25Okapi; print('deps OK')"
```
Expected: `deps OK`

### Step 3: Commit

```bash
git add pyproject.toml
git commit -m "feat(memory): add fastembed + rank-bm25 dependencies"
```

---

## Task 2: Core Memory module

**Files:**
- Create: `marneo/memory/__init__.py`
- Create: `marneo/memory/core.py`
- Create: `tests/memory/__init__.py`
- Create: `tests/memory/test_core.py`

### Step 1: Write failing tests

```python
# tests/memory/test_core.py
import pytest
from pathlib import Path
from marneo.memory.core import CoreMemory


def test_load_empty_when_no_file(tmp_path):
    cm = CoreMemory(tmp_path / "core.md")
    assert cm.content == ""
    assert cm.as_prompt() == ""


def test_add_and_load(tmp_path):
    cm = CoreMemory(tmp_path / "core.md")
    cm.add("API key 不能提交到 git", source="manual")
    cm2 = CoreMemory(tmp_path / "core.md")
    assert "API key 不能提交到 git" in cm2.content


def test_as_prompt_includes_header(tmp_path):
    cm = CoreMemory(tmp_path / "core.md")
    cm.add("绝对不删生产数据库", source="manual")
    prompt = cm.as_prompt()
    assert "# 核心记忆" in prompt
    assert "绝对不删生产数据库" in prompt


def test_enforces_char_limit(tmp_path):
    cm = CoreMemory(tmp_path / "core.md", max_chars=100)
    cm.add("A" * 200, source="manual")
    assert len(cm.as_prompt()) <= 150  # header + truncation notice


def test_list_entries(tmp_path):
    cm = CoreMemory(tmp_path / "core.md")
    cm.add("rule 1", source="manual")
    cm.add("rule 2", source="llm")
    entries = cm.list_entries()
    assert len(entries) == 2
    assert any("rule 1" in e["content"] for e in entries)
```

### Step 2: Verify FAIL

```bash
cd /Users/chamber/code/marneo-agent && pytest tests/memory/test_core.py -v 2>&1 | head -15
```

### Step 3: Implement

Create `marneo/memory/__init__.py` (empty).

Create `marneo/memory/core.py`:

```python
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

    # ── Internal helpers ──────────────────────────────────────────────

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

    # ── Public API ────────────────────────────────────────────────────

    @property
    def content(self) -> str:
        _, entries = self._load()
        return "\n".join(e["content"] for e in entries)

    def list_entries(self) -> list[dict]:
        _, entries = self._load()
        return entries

    def add(self, content: str, source: str = "manual") -> None:
        _, entries = self._load()
        # Avoid exact duplicates
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
```

### Step 4: Verify PASS

```bash
pytest tests/memory/test_core.py -v
```
Expected: 5 passed

### Step 5: Commit

```bash
git add marneo/memory/ tests/memory/
git commit -m "feat(memory): add CoreMemory — always-loaded critical constraints"
```

---

## Task 3: Episode Store (SQLite)

**Files:**
- Create: `marneo/memory/episodes.py`
- Create: `tests/memory/test_episodes.py`

### Step 1: Write failing tests

```python
# tests/memory/test_episodes.py
import pytest
from pathlib import Path
from marneo.memory.episodes import EpisodeStore, Episode


def test_add_and_get(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    ep = Episode(content="用 pd.read_csv(encoding='utf-8-sig') 处理飞书导出", type="discovery", tags=["pandas", "feishu"])
    ep_id = store.add(ep)
    assert ep_id.startswith("ep_")
    result = store.get(ep_id)
    assert result is not None
    assert result.content == ep.content


def test_list_recent(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    store.add(Episode(content="fact 1", type="decision"))
    store.add(Episode(content="fact 2", type="preference"))
    store.add(Episode(content="fact 3", type="advice"))
    recent = store.list_recent(limit=2)
    assert len(recent) == 2


def test_increment_access(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    ep_id = store.add(Episode(content="test", type="general"))
    store.increment_access(ep_id)
    store.increment_access(ep_id)
    ep = store.get(ep_id)
    assert ep.access_count == 2


def test_get_promotion_candidates(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    ep_id = store.add(Episode(content="frequently used", type="preference"))
    for _ in range(5):
        store.increment_access(ep_id)
    candidates = store.get_promotion_candidates(min_access=5)
    assert any(c.id == ep_id for c in candidates)


def test_mark_promoted(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    ep_id = store.add(Episode(content="x", type="general"))
    store.mark_promoted(ep_id)
    ep = store.get(ep_id)
    assert ep.promoted_to_core is True
```

### Step 2: Verify FAIL

```bash
pytest tests/memory/test_episodes.py -v 2>&1 | head -15
```

### Step 3: Implement `marneo/memory/episodes.py`

```python
# marneo/memory/episodes.py
"""Episodic Memory store — SQLite backend for work experience and skill index."""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Episode:
    content: str
    type: str = "general"         # decision/preference/discovery/problem/advice/general
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
        ep_id = ep.id or f"ep_{int(time.time() * 1000)}"
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
            conn.execute("UPDATE episodes SET access_count = access_count + 1 WHERE id=?", (ep_id,))

    def get_promotion_candidates(self, min_access: int = 5) -> list[Episode]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE access_count >= ? AND promoted_to_core = 0",
                (min_access,),
            ).fetchall()
        return [self._row_to_episode(r) for r in rows]

    def mark_promoted(self, ep_id: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE episodes SET promoted_to_core=1 WHERE id=?", (ep_id,))

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]

    @classmethod
    def for_employee(cls, employee_name: str) -> "EpisodeStore":
        from marneo.core.paths import get_marneo_dir
        db_path = get_marneo_dir() / "employees" / employee_name / "memory" / "episodes" / "index.db"
        return cls(db_path)
```

### Step 4: Verify PASS

```bash
pytest tests/memory/test_episodes.py -v
```
Expected: 5 passed

### Step 5: Commit

```bash
git add marneo/memory/episodes.py tests/memory/test_episodes.py
git commit -m "feat(memory): add EpisodeStore — SQLite backend for episodic memory"
```

---

## Task 4: Skill Indexer

**Files:**
- Create: `marneo/memory/skill_index.py`
- Create: `tests/memory/test_skill_index.py`

### Step 1: Write failing tests

```python
# tests/memory/test_skill_index.py
import pytest
from pathlib import Path
from marneo.memory.skill_index import index_skills_into_store
from marneo.memory.episodes import EpisodeStore


def test_index_skills_from_dir(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    # Write a skill file
    (skills_dir / "pandas-encoding.md").write_text(
        "---\nname: pandas 编码处理\ndescription: 处理飞书导出 UTF-8 编码问题\nenabled: true\n---\n\n解决方案内容",
        encoding="utf-8",
    )
    (skills_dir / "disabled-skill.md").write_text(
        "---\nname: 禁用技能\ndescription: 不应该被索引\nenabled: false\n---\n内容",
        encoding="utf-8",
    )

    store = EpisodeStore(tmp_path / "episodes.db")
    count = index_skills_into_store(skills_dir, store)

    assert count == 1  # only enabled skill
    episodes = store.list_recent(source="skill")
    assert len(episodes) == 1
    assert "pandas 编码处理" in episodes[0].content
    assert episodes[0].skill_id == "pandas-encoding"


def test_index_skills_idempotent(tmp_path):
    """Re-indexing same skills doesn't create duplicates."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "s1.md").write_text(
        "---\nname: skill one\ndescription: does X\nenabled: true\n---\ncontent",
        encoding="utf-8",
    )

    store = EpisodeStore(tmp_path / "episodes.db")
    index_skills_into_store(skills_dir, store)
    index_skills_into_store(skills_dir, store)  # second time

    episodes = store.list_recent(source="skill")
    assert len(episodes) == 1  # no duplicates
```

### Step 2: Verify FAIL

```bash
pytest tests/memory/test_skill_index.py -v 2>&1 | head -15
```

### Step 3: Implement `marneo/memory/skill_index.py`

```python
# marneo/memory/skill_index.py
"""Skill indexer — indexes ~/.marneo/skills/*.md into EpisodeStore.

Only stores name + description (not full content) for retrieval.
Full content is loaded on-demand via get_skill(skill_id).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from marneo.memory.episodes import EpisodeStore, Episode

log = logging.getLogger(__name__)


def _parse_skill_meta(path: Path) -> dict[str, Any] | None:
    """Extract YAML frontmatter from skill .md file."""
    try:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        end = text.find("---", 3)
        if end == -1:
            return None
        meta = yaml.safe_load(text[3:end]) or {}
        meta["_path"] = path
        return meta
    except Exception as e:
        log.debug("Failed to parse skill %s: %s", path, e)
        return None


def index_skills_into_store(skills_dir: Path, store: EpisodeStore) -> int:
    """Index all enabled skills from skills_dir into store.

    Only name + description are stored as the searchable content.
    Full skill content is always read from disk on-demand.

    Returns number of skills indexed.
    """
    if not skills_dir.exists():
        return 0

    # Get existing skill IDs in store to avoid duplicates
    existing = {ep.skill_id for ep in store.list_recent(limit=10000, source="skill")}

    count = 0
    for path in sorted(skills_dir.glob("*.md")):
        meta = _parse_skill_meta(path)
        if not meta:
            continue
        if not meta.get("enabled", True):
            continue

        skill_id = path.stem
        name = str(meta.get("name", skill_id))
        description = str(meta.get("description", ""))

        if skill_id in existing:
            continue  # already indexed, skip

        # Index only name + description (NOT full content)
        searchable = f"{name}。{description}" if description else name
        ep = Episode(
            id=f"skill_{skill_id}",
            content=searchable,
            type="skill",
            source="skill",
            skill_id=skill_id,
            tags=[],
            importance=0.7,
        )
        store.add(ep)
        count += 1

    log.info("[SkillIndex] Indexed %d skills from %s", count, skills_dir)
    return count


def get_skill_content(skill_id: str) -> str:
    """Read full content of a skill file from disk."""
    from marneo.core.paths import get_marneo_dir
    path = get_marneo_dir() / "skills" / f"{skill_id}.md"
    if not path.exists():
        return f"[Skill not found: {skill_id}]"
    return path.read_text(encoding="utf-8").strip()


def rebuild_skill_index(employee_name: str) -> int:
    """Rebuild skill index for an employee. Returns count indexed."""
    from marneo.core.paths import get_marneo_dir
    from marneo.project.workspace import get_employee_projects

    store = EpisodeStore.for_employee(employee_name)

    # Remove all existing skill entries
    all_eps = store.get_all()
    for ep in all_eps:
        if ep.source == "skill":
            store.mark_promoted(ep.id)  # use mark to soft-delete

    global_skills_dir = get_marneo_dir() / "skills"
    count = index_skills_into_store(global_skills_dir, store)

    # Also index project-specific skills
    try:
        projects = get_employee_projects(employee_name)
        from marneo.core.paths import get_projects_dir
        for proj in projects:
            proj_skills_dir = get_projects_dir() / proj.name / "skills"
            count += index_skills_into_store(proj_skills_dir, store)
    except Exception:
        pass

    return count
```

### Step 4: Verify PASS

```bash
pytest tests/memory/test_skill_index.py -v
```
Expected: 2 passed

### Step 5: Commit

```bash
git add marneo/memory/skill_index.py tests/memory/test_skill_index.py
git commit -m "feat(memory): add skill indexer — name+description only, content on-demand"
```

---

## Task 5: Hybrid Retriever (BM25 + fastembed)

**Files:**
- Create: `marneo/memory/retriever.py`
- Create: `tests/memory/test_retriever.py`

### Step 1: Write failing tests

```python
# tests/memory/test_retriever.py
import pytest
from pathlib import Path
from marneo.memory.episodes import EpisodeStore, Episode
from marneo.memory.retriever import HybridRetriever


@pytest.fixture
def store_with_episodes(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    store.add(Episode(id="ep1", content="Python pandas 处理 UTF-8 编码问题", type="discovery", tags=["pandas"]))
    store.add(Episode(id="ep2", content="Git 提交前必须检查 API key 泄露", type="preference", tags=["git", "security"]))
    store.add(Episode(id="ep3", content="飞书 Bitable 多维表格创建记录方法", type="advice", tags=["feishu", "bitable"]))
    store.add(Episode(id="ep4", content="Docker 部署时需要设置环境变量", type="decision", tags=["docker"]))
    return store


def test_retrieve_relevant(store_with_episodes, tmp_path):
    retriever = HybridRetriever(store_with_episodes, tmp_path / "vectors.npz")
    retriever.rebuild_index()
    results = retriever.retrieve("pandas 数据处理编码", n=2)
    assert len(results) > 0
    assert any("pandas" in r.content for r in results)


def test_retrieve_returns_at_most_n(store_with_episodes, tmp_path):
    retriever = HybridRetriever(store_with_episodes, tmp_path / "vectors.npz")
    retriever.rebuild_index()
    results = retriever.retrieve("任何问题", n=2)
    assert len(results) <= 2


def test_retrieve_empty_store(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    retriever = HybridRetriever(store, tmp_path / "vectors.npz")
    retriever.rebuild_index()
    results = retriever.retrieve("pandas", n=3)
    assert results == []


def test_bm25_only_fallback(store_with_episodes, tmp_path):
    """When vectors not built, BM25 alone should work."""
    retriever = HybridRetriever(store_with_episodes, tmp_path / "vectors.npz")
    # Don't call rebuild_index — test BM25-only path
    results = retriever.retrieve_bm25("pandas 编码", n=2)
    assert len(results) > 0
```

### Step 2: Verify FAIL

```bash
pytest tests/memory/test_retriever.py -v 2>&1 | head -15
```

### Step 3: Implement `marneo/memory/retriever.py`

```python
# marneo/memory/retriever.py
"""Hybrid BM25 + fastembed retriever for episodic memory.

Pattern ported from mempalace: vector search is the floor,
BM25 re-ranks within candidates.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
from rank_bm25 import BM25Okapi

from marneo.memory.episodes import Episode, EpisodeStore

log = logging.getLogger(__name__)

_EMBED_MODEL = "BAAI/bge-small-zh-v1.5"  # ~50MB, Chinese + English, no GPU


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: split on whitespace + CJK chars."""
    import re
    tokens = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower())
    return tokens or [text]


class HybridRetriever:
    """BM25 + fastembed vector hybrid retrieval.

    Build flow:
      rebuild_index() → loads all episodes → builds BM25 + vectors
    Retrieve flow:
      retrieve(query) → vector floor → BM25 rerank → top-n
    """

    def __init__(self, store: EpisodeStore, vectors_path: Path) -> None:
        self._store = store
        self._vectors_path = vectors_path
        self._episodes: list[Episode] = []
        self._bm25: Optional[BM25Okapi] = None
        self._vectors: Optional[np.ndarray] = None
        self._embedder = None  # lazy init

    def _get_embedder(self) -> Any:
        if self._embedder is None:
            try:
                from fastembed import TextEmbedding
                self._embedder = TextEmbedding(model_name=_EMBED_MODEL)
                log.info("[Memory] fastembed model loaded: %s", _EMBED_MODEL)
            except Exception as e:
                log.warning("[Memory] fastembed not available: %s", e)
        return self._embedder

    def rebuild_index(self) -> None:
        """Load all non-promoted episodes and build BM25 + vector index."""
        all_eps = self._store.get_all()
        self._episodes = [e for e in all_eps if not e.promoted_to_core]

        if not self._episodes:
            self._bm25 = None
            self._vectors = None
            return

        # Build BM25
        tokenized = [_tokenize(e.content) for e in self._episodes]
        self._bm25 = BM25Okapi(tokenized)

        # Build vectors (lazy — only if fastembed available)
        embedder = self._get_embedder()
        if embedder is not None:
            try:
                texts = [e.content for e in self._episodes]
                vecs = list(embedder.embed(texts))
                self._vectors = np.array(vecs, dtype=np.float32)
                # Normalize for cosine similarity
                norms = np.linalg.norm(self._vectors, axis=1, keepdims=True)
                norms = np.where(norms == 0, 1, norms)
                self._vectors = self._vectors / norms
                # Cache to disk
                self._vectors_path.parent.mkdir(parents=True, exist_ok=True)
                np.save(str(self._vectors_path), self._vectors)
            except Exception as e:
                log.warning("[Memory] Vector build failed: %s", e)
                self._vectors = None

    def _load_cached_vectors(self) -> Optional[np.ndarray]:
        if self._vectors_path.exists():
            try:
                return np.load(str(self._vectors_path))
            except Exception:
                pass
        return None

    def retrieve(self, query: str, n: int = 3, threshold: float = 0.0) -> list[Episode]:
        """Hybrid retrieve: vector floor + BM25 rerank."""
        if not self._episodes:
            return []

        # Ensure index is built
        if self._bm25 is None:
            self.rebuild_index()
        if not self._episodes:
            return []

        embedder = self._get_embedder()
        if embedder is not None and self._vectors is not None:
            try:
                # Vector search (cosine similarity)
                q_vec = np.array(list(embedder.embed([query]))[0], dtype=np.float32)
                q_norm = np.linalg.norm(q_vec)
                if q_norm > 0:
                    q_vec = q_vec / q_norm
                scores = self._vectors @ q_vec  # cosine similarity
                # Over-fetch for reranking
                top_k = min(n * 3, len(self._episodes))
                top_idx = np.argsort(scores)[::-1][:top_k].tolist()
                candidates = [self._episodes[i] for i in top_idx]
                candidate_scores = {self._episodes[i].id: float(scores[i]) for i in top_idx}
            except Exception as e:
                log.warning("[Memory] Vector retrieval failed: %s", e)
                candidates = self._episodes
                candidate_scores = {}
        else:
            # No vectors — use all as candidates
            candidates = self._episodes
            candidate_scores = {}

        # BM25 rerank within candidates
        if self._bm25 and candidates:
            q_tokens = _tokenize(query)
            # Get BM25 scores for candidate indices
            all_bm25 = self._bm25.get_scores(q_tokens)
            candidate_ids = {e.id for e in candidates}
            # Combine scores
            combined: list[tuple[float, Episode]] = []
            for ep in candidates:
                idx = next((i for i, e in enumerate(self._episodes) if e.id == ep.id), -1)
                if idx == -1:
                    continue
                bm25_score = float(all_bm25[idx]) / (max(all_bm25) + 1e-8) if max(all_bm25) > 0 else 0.0
                vec_score = candidate_scores.get(ep.id, 0.0)
                # Weighted combination: 60% vector + 40% BM25
                final_score = 0.6 * vec_score + 0.4 * bm25_score
                combined.append((final_score, ep))
            combined.sort(key=lambda x: x[0], reverse=True)
            results = [ep for score, ep in combined if score >= threshold][:n]
        else:
            results = candidates[:n]

        # Increment access count for retrieved episodes
        for ep in results:
            self._store.increment_access(ep.id)

        return results

    def retrieve_bm25(self, query: str, n: int = 3) -> list[Episode]:
        """BM25-only retrieval (fallback when vectors not available)."""
        if not self._episodes:
            return []
        if self._bm25 is None:
            tokenized = [_tokenize(e.content) for e in self._episodes]
            self._bm25 = BM25Okapi(tokenized)
        q_tokens = _tokenize(query)
        scores = self._bm25.get_scores(q_tokens)
        top_idx = np.argsort(scores)[::-1][:n].tolist()
        return [self._episodes[i] for i in top_idx if scores[i] > 0]

    @classmethod
    def for_employee(cls, employee_name: str) -> "HybridRetriever":
        from marneo.core.paths import get_marneo_dir
        base = get_marneo_dir() / "employees" / employee_name / "memory" / "episodes"
        store = EpisodeStore(base / "index.db")
        return cls(store, base / "vectors.npy")
```

Add `from typing import Any` at the top of the file.

### Step 4: Verify PASS

```bash
pytest tests/memory/test_retriever.py -v
```
Expected: 4 passed (note: test_retrieve_relevant may take ~10s first run for model download)

### Step 5: Commit

```bash
git add marneo/memory/retriever.py tests/memory/test_retriever.py
git commit -m "feat(memory): add HybridRetriever — BM25 + fastembed vector search"
```

---

## Task 6: Memory Tools (recall_memory, get_skill, add_core_memory, add_episode)

**Files:**
- Create: `marneo/tools/core/memory_tools.py`
- Create: `tests/tools/test_memory_tools.py`

### Step 1: Write failing tests

```python
# tests/tools/test_memory_tools.py
import json
import pytest
from unittest.mock import patch, MagicMock
from marneo.tools.core.memory_tools import recall_memory, get_skill, add_core_memory


def test_recall_memory_empty(tmp_path):
    """recall_memory returns empty list when no episodes."""
    from marneo.memory.episodes import EpisodeStore
    from marneo.memory.retriever import HybridRetriever
    store = EpisodeStore(tmp_path / "ep.db")
    retriever = HybridRetriever(store, tmp_path / "v.npy")
    retriever.rebuild_index()
    result = json.loads(recall_memory({"query": "pandas"}, _retriever=retriever))
    assert result["results"] == []


def test_add_core_memory_writes_file(tmp_path):
    from marneo.memory.core import CoreMemory
    cm = CoreMemory(tmp_path / "core.md")
    result = json.loads(add_core_memory(
        {"content": "绝对不删除生产数据", "reason": "测试"},
        _core_memory=cm,
    ))
    assert result["ok"] is True
    assert "绝对不删除生产数据" in cm.content


def test_get_skill_not_found():
    result = json.loads(get_skill({"skill_id": "nonexistent-xyz-123"}))
    # Should return error or not-found message, not crash
    assert "error" in result or "not found" in result.get("content", "").lower()
```

### Step 2: Verify FAIL

```bash
pytest tests/tools/test_memory_tools.py -v 2>&1 | head -15
```

### Step 3: Implement `marneo/tools/core/memory_tools.py`

```python
# marneo/tools/core/memory_tools.py
"""Memory tools: recall_memory, get_skill, add_core_memory, add_episode.

These tools are NOT registered globally — they are injected per-session
with employee-specific memory objects. See memory/session_memory.py.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from marneo.tools.registry import registry, tool_result, tool_error


def recall_memory(
    args: dict[str, Any],
    _retriever: Any = None,
    **kw: Any,
) -> str:
    """Retrieve relevant memories by query."""
    query = args.get("query", "").strip()
    n = min(int(args.get("n", 3)), 5)
    filter_type = args.get("type", "")  # "skill" | "episode" | ""

    if not query:
        return tool_error("query is required")

    if _retriever is None:
        return tool_result(results=[], note="Memory system not initialized for this session")

    try:
        results = _retriever.retrieve(query, n=n)
        if filter_type:
            results = [r for r in results if r.source == filter_type]

        items = []
        for ep in results:
            items.append({
                "id": ep.id,
                "content": ep.content,
                "type": ep.type,
                "source": ep.source,
                "skill_id": ep.skill_id,
            })
        return tool_result(results=items, query=query)
    except Exception as exc:
        return tool_error(str(exc))


def get_skill(
    args: dict[str, Any],
    **kw: Any,
) -> str:
    """Get full content of a skill by ID."""
    skill_id = args.get("skill_id", "").strip()
    if not skill_id:
        return tool_error("skill_id is required")

    try:
        from marneo.memory.skill_index import get_skill_content
        content = get_skill_content(skill_id)
        if content.startswith("[Skill not found"):
            return tool_error(f"Skill not found: {skill_id}")
        return tool_result(skill_id=skill_id, content=content)
    except Exception as exc:
        return tool_error(str(exc))


def add_core_memory(
    args: dict[str, Any],
    _core_memory: Any = None,
    **kw: Any,
) -> str:
    """Write a new entry to core memory."""
    content = args.get("content", "").strip()
    reason = args.get("reason", "").strip()

    if not content:
        return tool_error("content is required")

    if _core_memory is None:
        return tool_error("Core memory not available for this session")

    try:
        _core_memory.add(content, source="llm")
        return tool_result(ok=True, content=content, reason=reason)
    except Exception as exc:
        return tool_error(str(exc))


def add_episode(
    args: dict[str, Any],
    _store: Any = None,
    **kw: Any,
) -> str:
    """Write a new episodic memory entry."""
    content = args.get("content", "").strip()
    ep_type = args.get("type", "general")
    tags = args.get("tags", [])

    if not content:
        return tool_error("content is required")

    if _store is None:
        return tool_result(ok=True, note="Episode store not available, skipping")

    try:
        from marneo.memory.episodes import Episode
        ep = Episode(content=content, type=ep_type, tags=tags if isinstance(tags, list) else [])
        ep_id = _store.add(ep)
        return tool_result(ok=True, id=ep_id)
    except Exception as exc:
        return tool_error(str(exc))


# ── Tool schemas (for LLM tool calling) ──────────────────────────────────────

MEMORY_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Recall relevant work experience or skills by query. Use when you need to remember past solutions or find relevant skills.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "n": {"type": "integer", "description": "Max results (default 3)", "default": 3},
                    "type": {"type": "string", "description": "Filter: 'skill' or 'episode' (optional)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_skill",
            "description": "Get full content of a skill by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "description": "Skill file ID (without .md)"},
                },
                "required": ["skill_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_core_memory",
            "description": "Save a critical constraint or rule to core memory (never forgotten). Use when user states an important rule.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The rule or constraint to remember"},
                    "reason": {"type": "string", "description": "Why this is important"},
                },
                "required": ["content", "reason"],
            },
        },
    },
]
```

### Step 4: Verify PASS

```bash
pytest tests/tools/test_memory_tools.py -v
```
Expected: 3 passed

### Step 5: Commit

```bash
git add marneo/tools/core/memory_tools.py tests/tools/test_memory_tools.py
git commit -m "feat(memory): add memory tools — recall_memory, get_skill, add_core_memory"
```

---

## Task 7: Session Memory — per-session memory context

**Files:**
- Create: `marneo/memory/session_memory.py`
- Create: `tests/memory/test_session_memory.py`

### Step 1: Write failing tests

```python
# tests/memory/test_session_memory.py
import pytest
from pathlib import Path
from marneo.memory.session_memory import SessionMemory, ContextBudget


def test_budget_defaults():
    b = ContextBudget()
    assert b.system_prompt_max == 4000
    assert b.working_memory_turns == 20
    assert b.episodic_inject_max == 1500


def test_build_system_prompt_fixed_size(tmp_path):
    sm = SessionMemory.__new__(SessionMemory)
    sm._soul = "我是老七，一名专注的数字员工。"
    sm._core = type("C", (), {"as_prompt": lambda self: "## 核心记忆\n- 绝对不删数据"})()
    sm._retriever = None
    sm._budget = ContextBudget(system_prompt_max=200, core_memory_max=100)

    prompt = sm.build_system_prompt("", skip_retrieval=True)
    assert len(prompt) <= 300  # some slack for formatting
    assert "老七" in prompt
    assert "核心记忆" in prompt


def test_trim_working_memory():
    sm = SessionMemory.__new__(SessionMemory)
    sm._budget = ContextBudget(working_memory_turns=3)
    messages = [
        {"role": "user", "content": f"msg {i}"},
        {"role": "assistant", "content": f"reply {i}"},
    ] * 5  # 10 messages = 5 turns
    trimmed = sm.trim_working_memory(messages)
    # Should keep last 3 turns = 6 messages
    assert len(trimmed) == 6
    assert "msg 4" in trimmed[0]["content"]
```

### Step 2: Verify FAIL

```bash
pytest tests/memory/test_session_memory.py -v 2>&1 | head -15
```

### Step 3: Implement `marneo/memory/session_memory.py`

```python
# marneo/memory/session_memory.py
"""SessionMemory — per-session context builder with budget enforcement.

Replaces the unbounded system prompt assembly in session.py and work.py.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class ContextBudget:
    """Configurable context size limits (chars)."""
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
            raw = getattr(cfg, "context_budget", {}) or {}
            if not isinstance(raw, dict):
                return cls()
            return cls(
                system_prompt_max=int(raw.get("system_prompt_max", 4000)),
                core_memory_max=int(raw.get("core_memory_max", 1000)),
                working_memory_turns=int(raw.get("working_memory_turns", 20)),
                episodic_inject_max=int(raw.get("episodic_inject_max", 1500)),
                tool_result_max=int(raw.get("tool_result_max", 50_000)),
            )
        except Exception:
            return cls()


class SessionMemory:
    """Builds the system prompt and manages working memory for one session."""

    def __init__(
        self,
        employee_name: str,
        soul: str = "",
        budget: Optional[ContextBudget] = None,
    ) -> None:
        self._employee_name = employee_name
        self._soul = soul
        self._budget = budget or ContextBudget.from_config()

        # Lazy-loaded
        self._core: Any = None
        self._retriever: Any = None
        self._store: Any = None

    def _get_core(self) -> Any:
        if self._core is None:
            from marneo.memory.core import CoreMemory
            self._core = CoreMemory.for_employee(
                self._employee_name, self._budget.core_memory_max
            )
        return self._core

    def _get_retriever(self) -> Any:
        if self._retriever is None:
            try:
                from marneo.memory.retriever import HybridRetriever
                from marneo.memory.skill_index import index_skills_into_store, rebuild_skill_index
                from marneo.core.paths import get_marneo_dir

                retriever = HybridRetriever.for_employee(self._employee_name)
                store = retriever._store

                # Index skills if not done yet
                global_skills_dir = get_marneo_dir() / "skills"
                index_skills_into_store(global_skills_dir, store)

                retriever.rebuild_index()
                self._retriever = retriever
                self._store = store
            except Exception as e:
                log.warning("[SessionMemory] Retriever init failed: %s", e)
        return self._retriever

    def build_system_prompt(self, query: str = "", skip_retrieval: bool = False) -> str:
        """Build system prompt: SOUL + Core Memory (+ optional episodic injection).

        The episodic injection is returned separately via retrieve_for_turn().
        This method builds the FIXED part only.
        """
        parts: list[str] = []

        # 1. SOUL (identity)
        soul = self._soul.strip()
        if soul:
            remaining = self._budget.system_prompt_max - len(soul)
            if remaining < 200:
                # Soul is too long — truncate
                soul = soul[:self._budget.system_prompt_max - 200]
            parts.append(soul)

        # 2. Core Memory (always loaded)
        core_prompt = self._get_core().as_prompt()
        if core_prompt:
            parts.append(core_prompt)

        result = "\n\n".join(parts)

        # Enforce hard limit
        if len(result) > self._budget.system_prompt_max:
            result = result[:self._budget.system_prompt_max - 20] + "\n...(截断)"

        return result

    def retrieve_for_turn(self, query: str) -> str:
        """Retrieve relevant memories for current turn (episodic injection).

        Returns formatted string ready for injection, or "" if nothing relevant.
        """
        retriever = self._get_retriever()
        if retriever is None or not query.strip():
            return ""

        try:
            results = retriever.retrieve(query, n=3)
            if not results:
                return ""

            lines = ["# 相关经验（本轮参考，不保留）"]
            total_chars = len(lines[0])
            for ep in results:
                line = f"- {ep.content}"
                if total_chars + len(line) > self._budget.episodic_inject_max:
                    break
                lines.append(line)
                total_chars += len(line)

            return "\n".join(lines) if len(lines) > 1 else ""
        except Exception as e:
            log.debug("[SessionMemory] retrieve_for_turn error: %s", e)
            return ""

    def trim_working_memory(self, messages: list[dict]) -> list[dict]:
        """Trim messages to stay within working_memory_turns."""
        max_turns = self._budget.working_memory_turns
        # Count turns: each user+assistant pair = 1 turn
        # Find the start index for the last N turns
        turn_count = 0
        i = len(messages)
        while i > 0 and turn_count < max_turns:
            i -= 1
            if messages[i].get("role") == "assistant":
                turn_count += 1
        return messages[i:]

    def add_episode_from_turn(self, user_msg: str, assistant_reply: str) -> None:
        """Extract and save episode from a conversation turn (heuristic-based)."""
        if self._store is None:
            self._get_retriever()  # ensures store is initialized
        if self._store is None:
            return
        try:
            from marneo.memory.extractor import extract_episode
            ep = extract_episode(user_msg, assistant_reply)
            if ep:
                self._store.add(ep)
                log.debug("[SessionMemory] Episode extracted: %s", ep.content[:60])
        except Exception as e:
            log.debug("[SessionMemory] Episode extraction error: %s", e)

    def check_and_promote(self, min_access: int = 5) -> int:
        """Promote high-access episodes to core memory. Returns count promoted."""
        if self._store is None:
            return 0
        candidates = self._store.get_promotion_candidates(min_access=min_access)
        core = self._get_core()
        promoted = 0
        for ep in candidates:
            if len(core.content) + len(ep.content) < self._budget.core_memory_max:
                core.add(ep.content, source="promoted")
                self._store.mark_promoted(ep.id)
                promoted += 1
        return promoted

    def get_memory_tools(self) -> tuple[list[dict], dict]:
        """Return (tool_schemas, tool_handlers) for injection into ChatSession."""
        from marneo.tools.core.memory_tools import (
            MEMORY_TOOL_SCHEMAS, recall_memory, get_skill, add_core_memory, add_episode
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
```

### Step 4: Verify PASS

```bash
pytest tests/memory/test_session_memory.py -v
```
Expected: 3 passed

### Step 5: Commit

```bash
git add marneo/memory/session_memory.py tests/memory/test_session_memory.py
git commit -m "feat(memory): add SessionMemory — fixed-size prompt builder with context budget"
```

---

## Task 8: Heuristic Episode Extractor

**Files:**
- Create: `marneo/memory/extractor.py`
- Create: `tests/memory/test_extractor.py`

### Step 1: Write failing tests

```python
# tests/memory/test_extractor.py
from marneo.memory.extractor import extract_episode


def test_extracts_decision():
    ep = extract_episode(
        "用哪个库处理 PDF？",
        "我们决定用 pypdf 而不是 pdfminer，因为 API 更简单。"
    )
    assert ep is not None
    assert ep.type == "decision"
    assert "pypdf" in ep.content


def test_extracts_discovery():
    ep = extract_episode(
        "为什么 pandas 读取出错？",
        "发现是 UTF-8 编码问题，用 encoding='utf-8-sig' 解决了。"
    )
    assert ep is not None
    assert ep.type == "discovery"


def test_skips_short_reply():
    ep = extract_episode("你好", "你好！")
    assert ep is None


def test_skips_generic_reply():
    ep = extract_episode("怎么样？", "好的，我明白了。")
    assert ep is None


def test_extracts_preference():
    ep = extract_episode(
        "代码风格要求？",
        "始终用 Python，不用 JavaScript。所有函数要有类型注解。"
    )
    assert ep is not None
    assert ep.type == "preference"
```

### Step 2: Verify FAIL

```bash
pytest tests/memory/test_extractor.py -v 2>&1 | head -15
```

### Step 3: Implement `marneo/memory/extractor.py`

```python
# marneo/memory/extractor.py
"""Heuristic episode extractor — no LLM required.

Pattern: detect signal phrases → classify type → extract summary.
Ported from mempalace general_extractor.py pattern.
"""
from __future__ import annotations

import re
from typing import Optional

from marneo.memory.episodes import Episode

_MIN_REPLY_LEN = 50

# Signal patterns → memory type
_PATTERNS = [
    ("decision", [
        r"我们决定", r"选择了", r"用.+而不是", r"改用", r"决定用", r"最终选",
        r"we decided", r"chose to", r"switched to",
    ]),
    ("discovery", [
        r"发现是", r"原来是", r"原因是", r"问题在于", r"解决方案", r"解决了",
        r"found that", r"turns out", r"figured out", r"the issue was",
    ]),
    ("preference", [
        r"始终", r"一律", r"不要用", r"必须", r"约定", r"规范", r"风格",
        r"always use", r"never do", r"convention", r"must be",
    ]),
    ("problem", [
        r"出错了", r"报错", r"失败", r"bug", r"问题是", r"错误",
        r"error", r"failed", r"broken", r"crash",
    ]),
    ("advice", [
        r"建议", r"推荐", r"最好", r"注意", r"记得", r"tip",
        r"recommend", r"suggest", r"best practice",
    ]),
]


def _detect_type(text: str) -> Optional[str]:
    text_lower = text.lower()
    for mem_type, patterns in _PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return mem_type
    return None


def _extract_summary(reply: str, max_len: int = 200) -> str:
    """Extract the most informative sentence(s) from a reply."""
    # Split into sentences
    sentences = re.split(r"[。！？\n]", reply)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    if not sentences:
        return reply[:max_len]
    # Take first 2 meaningful sentences
    summary = "。".join(sentences[:2])
    if len(summary) > max_len:
        summary = summary[:max_len]
    return summary


def extract_episode(user_msg: str, assistant_reply: str) -> Optional[Episode]:
    """Extract an episode from a conversation turn.

    Returns None if the reply is too short or generic.
    No LLM call required — heuristic pattern matching only.
    """
    if len(assistant_reply) < _MIN_REPLY_LEN:
        return None

    mem_type = _detect_type(assistant_reply)
    if mem_type is None:
        return None  # no signal phrases found

    summary = _extract_summary(assistant_reply)

    # Extract simple tags from user message keywords
    tags = re.findall(r"[a-zA-Z][a-zA-Z0-9_\-\.]{2,}", user_msg + " " + assistant_reply)
    tags = list(dict.fromkeys(t.lower() for t in tags if len(t) < 30))[:5]

    return Episode(
        content=summary,
        type=mem_type,
        source="episode",
        tags=tags,
    )
```

### Step 4: Verify PASS

```bash
pytest tests/memory/test_extractor.py -v
```
Expected: 5 passed

### Step 5: Commit

```bash
git add marneo/memory/extractor.py tests/memory/test_extractor.py
git commit -m "feat(memory): add heuristic episode extractor — no LLM required"
```

---

## Task 9: Refactor session.py + work.py to use SessionMemory

**Files:**
- Modify: `marneo/gateway/session.py` — use SessionMemory
- Modify: `marneo/cli/work.py` — use SessionMemory, remove skills injection

### Step 1: Read both files

```bash
cat /Users/chamber/code/marneo-agent/marneo/gateway/session.py
grep -n "skills\|soul\|project\|base_system" /Users/chamber/code/marneo-agent/marneo/cli/work.py
```

### Step 2: Modify `marneo/gateway/session.py`

Replace `_create_engine()` to use `SessionMemory.build_system_prompt()` instead of injecting all skills/projects inline:

```python
    async def _create_engine(self, platform: str = "") -> Any:
        from marneo.engine.chat import ChatSession

        base_system = "你是一名专注的数字员工，通过 IM 渠道与用户协作。保持专业、简洁的沟通风格。"

        if ":" in platform:
            emp_name = platform.split(":", 1)[1]
            try:
                from marneo.memory.session_memory import SessionMemory
                from marneo.employee.profile import load_profile
                from marneo.employee.growth import build_level_directive

                profile = load_profile(emp_name)
                soul = ""
                if profile and profile.soul_path.exists():
                    soul = profile.soul_path.read_text(encoding="utf-8").strip()
                if profile:
                    directive = build_level_directive(profile)
                    if directive:
                        soul = f"{soul}\n\n{directive}" if soul else directive

                sm = SessionMemory(emp_name, soul=soul)
                system_prompt = sm.build_system_prompt()
                engine = ChatSession(system_prompt=system_prompt)
                engine._session_memory = sm  # attach for later use
                return engine
            except Exception as e:
                log.warning("[Session] SessionMemory init failed for %s: %s", emp_name, e)

        return ChatSession(system_prompt=base_system)
```

### Step 3: Modify `marneo/cli/work.py`

Find the system prompt building block (lines with `base_system`, `soul`, `skills_ctx`) and replace with:

```python
    # Build system prompt via SessionMemory
    from marneo.memory.session_memory import SessionMemory
    soul = ""
    if profile and profile.soul_path.exists():
        soul = profile.soul_path.read_text(encoding="utf-8").strip()
    if profile:
        directive = build_level_directive(profile)
        if directive:
            soul = f"{soul}\n\n{directive}" if soul else directive

    _session_memory = SessionMemory(employee_name, soul=soul)
    base_system = _session_memory.build_system_prompt()
    session = ChatSession(system_prompt=base_system)
    session._session_memory = _session_memory
```

Remove the old `# Inject skills` block entirely.

Also update `on_input` to add episode extraction after each turn:

```python
        # After getting reply, extract episode
        if reply.strip() and len(reply) > 50:
            try:
                _session_memory.add_episode_from_turn(text, reply)
            except Exception:
                pass
```

### Step 4: Run full tests

```bash
pytest tests/ -q --tb=short
```
Expected: all pass

### Step 5: Commit

```bash
git add marneo/gateway/session.py marneo/cli/work.py
git commit -m "feat(memory): refactor session.py + work.py to use SessionMemory"
```

---

## Task 10: Config support for context_budget

**Files:**
- Modify: `marneo/core/config.py` — add `context_budget` field

### Step 1: Read config.py

```bash
cat /Users/chamber/code/marneo-agent/marneo/core/config.py
```

### Step 2: Add `ContextBudgetConfig` and wire into `MarneoConfig`

Add to `config.py`:

```python
@dataclass
class ContextBudgetConfig:
    system_prompt_max: int = 4000
    core_memory_max: int = 1000
    working_memory_turns: int = 20
    episodic_inject_max: int = 1500
    tool_result_max: int = 50_000
```

Add `context_budget: ContextBudgetConfig = field(default_factory=ContextBudgetConfig)` to `MarneoConfig`.

In `load_config()`, parse the `context_budget:` section from YAML.

### Step 3: Update `ContextBudget.from_config()` in session_memory.py

The `from_config()` method already reads from config — verify it works:

```bash
python3 -c "
from marneo.memory.session_memory import ContextBudget
b = ContextBudget.from_config()
print('budget:', b)
"
```

### Step 4: Commit

```bash
git add marneo/core/config.py marneo/memory/session_memory.py
git commit -m "feat(memory): add context_budget config support"
```

---

## Task 11: CLI memory commands

**Files:**
- Create: `marneo/cli/memory_cmd.py`
- Modify: `marneo/cli/app.py` — register memory command

### Step 1: Create `marneo/cli/memory_cmd.py`

```python
# marneo/cli/memory_cmd.py
"""marneo memory — memory management commands."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

console = Console()
memory_app = typer.Typer(help="记忆管理。")


@memory_app.command("add")
def cmd_add(
    content: str = typer.Argument(..., help="要记住的内容"),
    name: str = typer.Option(..., "--employee", "-e", help="员工名称"),
    core: bool = typer.Option(False, "--core", help="写入核心记忆（永远加载）"),
) -> None:
    """为员工添加记忆条目。"""
    from marneo.memory.core import CoreMemory
    from marneo.memory.episodes import EpisodeStore, Episode

    if core:
        cm = CoreMemory.for_employee(name)
        cm.add(content, source="manual")
        console.print(f"[green]✓ 已写入核心记忆：{content[:60]}[/green]")
    else:
        store = EpisodeStore.for_employee(name)
        ep = Episode(content=content, type="general", source="episode")
        ep_id = store.add(ep)
        console.print(f"[green]✓ 已写入经验记忆 [{ep_id}]：{content[:60]}[/green]")


@memory_app.command("list")
def cmd_list(
    name: str = typer.Option(..., "--employee", "-e", help="员工名称"),
    core: bool = typer.Option(False, "--core", help="只显示核心记忆"),
    n: int = typer.Option(20, "-n", help="显示最近 N 条经验"),
) -> None:
    """列出员工的记忆条目。"""
    if core:
        from marneo.memory.core import CoreMemory
        cm = CoreMemory.for_employee(name)
        entries = cm.list_entries()
        if not entries:
            console.print("[dim]暂无核心记忆。[/dim]")
            return
        t = Table(title=f"{name} 核心记忆", show_header=True, header_style="bold #FFD700")
        t.add_column("内容")
        t.add_column("来源", style="dim")
        for e in entries:
            t.add_row(e["content"], e.get("source", "manual"))
        console.print(t)
    else:
        from marneo.memory.episodes import EpisodeStore
        store = EpisodeStore.for_employee(name)
        episodes = store.list_recent(limit=n)
        if not episodes:
            console.print("[dim]暂无经验记忆。[/dim]")
            return
        t = Table(title=f"{name} 经验记忆（最近 {n} 条）", show_header=True, header_style="bold #FFD700")
        t.add_column("ID", style="dim")
        t.add_column("内容")
        t.add_column("类型", style="dim")
        t.add_column("来源", style="dim")
        t.add_column("召回", justify="right", style="dim")
        for ep in episodes:
            t.add_row(ep.id[:12], ep.content[:60], ep.type, ep.source, str(ep.access_count))
        console.print(t)


@memory_app.command("stats")
def cmd_stats(
    name: str = typer.Option(..., "--employee", "-e", help="员工名称"),
) -> None:
    """查看记忆库统计。"""
    from marneo.memory.core import CoreMemory
    from marneo.memory.episodes import EpisodeStore

    cm = CoreMemory.for_employee(name)
    core_entries = cm.list_entries()
    store = EpisodeStore.for_employee(name)
    total = store.count()
    skills = len([e for e in store.list_recent(limit=10000, source="skill")])
    episodes = total - skills

    console.print(f"\n[bold #FF6611]{name} 记忆统计[/bold #FF6611]")
    console.print(f"  核心记忆条目：{len(core_entries)} 条")
    console.print(f"  经验记忆：{episodes} 条")
    console.print(f"  技能索引：{skills} 条")
    console.print(f"  总计：{total} 条\n")


@memory_app.command("rebuild")
def cmd_rebuild(
    name: str = typer.Option(..., "--employee", "-e", help="员工名称"),
) -> None:
    """重建技能索引 + 向量索引。"""
    from marneo.memory.skill_index import rebuild_skill_index
    from marneo.memory.retriever import HybridRetriever

    console.print("[dim]重建技能索引...[/dim]")
    count = rebuild_skill_index(name)
    console.print(f"[dim]索引了 {count} 个技能。重建向量索引...[/dim]")

    retriever = HybridRetriever.for_employee(name)
    retriever.rebuild_index()
    console.print(f"[green]✓ 重建完成（{count} 个技能）[/green]")
```

### Step 2: Register in `app.py`

Read `marneo/cli/app.py`, then add:
```python
from marneo.cli.memory_cmd import memory_app
app.add_typer(memory_app, name="memory")
```

### Step 3: Verify CLI works

```bash
marneo memory --help
marneo memory stats --employee 老七
```

### Step 4: Commit

```bash
git add marneo/cli/memory_cmd.py marneo/cli/app.py
git commit -m "feat(memory): add marneo memory CLI commands (add/list/stats/rebuild)"
```

---

## Task 12: Smoke test + final verification

### Step 1: Run full test suite

```bash
cd /Users/chamber/code/marneo-agent && pytest tests/ -q --tb=short
```
Expected: all pass

### Step 2: Verify system prompt size

```bash
python3 -c "
from marneo.memory.session_memory import SessionMemory, ContextBudget

sm = SessionMemory('test_emp', soul='我是测试员工，专注工作。')
prompt = sm.build_system_prompt(skip_retrieval=True)
print(f'System prompt chars: {len(prompt)}')
assert len(prompt) <= 4000, f'Too large: {len(prompt)}'
print('✓ System prompt within budget')
"
```

### Step 3: Verify skill indexing

```bash
python3 -c "
from marneo.tools.loader import load_all_tools
load_all_tools()
from marneo.tools.registry import registry
tools = [d['function']['name'] for d in registry.get_definitions()]
print('Tools:', tools)
assert 'recall_memory' not in tools  # memory tools are session-scoped, not global
print('✓ recall_memory correctly NOT in global registry')
"
```

### Step 4: Final commit

```bash
git add -A
git commit -m "feat(memory): complete 3-tier memory system — Core/Episodic/Working with hybrid retrieval"
git push
```

---

## Summary

After all tasks, marneo has:

| Component | Files | Purpose |
|---|---|---|
| `memory/core.py` | `CoreMemory` | Always-loaded constraints, 3 write paths |
| `memory/episodes.py` | `EpisodeStore` | SQLite backend for work experience |
| `memory/skill_index.py` | `index_skills_into_store` | Skills as searchable index (name+desc only) |
| `memory/retriever.py` | `HybridRetriever` | BM25 + fastembed vector search |
| `memory/session_memory.py` | `SessionMemory` | Fixed-size prompt builder + budget enforcement |
| `memory/extractor.py` | `extract_episode` | Heuristic episode extraction (no LLM) |
| `tools/core/memory_tools.py` | `recall_memory`, `get_skill`, etc. | LLM-callable memory tools |
| `cli/memory_cmd.py` | `marneo memory` | CLI for memory management |

**Context budget result:**

| Metric | Before | After |
|---|---|---|
| System prompt (base) | Unbounded | ≤ 4,000 chars |
| 100 skills impact | +50,000 chars | 0 chars |
| Skills loading | All upfront | On-demand via retrieval |
| OpenClaw comparison | — | OpenClaw: ~40,000 chars fixed |
