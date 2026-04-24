# marneo/memory/skill_index.py
"""Skill indexer — indexes ~/.marneo/skills/*.md into EpisodeStore.

Only stores name + description (not full content) for retrieval.
Full content is loaded on-demand via get_skill_content().
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from marneo.memory.episodes import EpisodeStore, Episode

log = logging.getLogger(__name__)


def _parse_skill_meta(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        end = text.find("---", 3)
        if end == -1:
            return None
        meta = yaml.safe_load(text[3:end]) or {}
        return meta
    except Exception as e:
        log.debug("Failed to parse skill %s: %s", path, e)
        return None


def index_skills_into_store(skills_dir: Path, store: EpisodeStore) -> int:
    """Index all enabled skills from skills_dir into store.

    Only name + description are stored as the searchable content.
    Full skill content is always read from disk on-demand.
    Returns number of skills newly indexed.
    """
    if not skills_dir.exists():
        return 0

    existing = {ep.skill_id for ep in store.list_recent(limit=10000, source="skill")}

    count = 0
    for path in sorted(skills_dir.glob("*.md")):
        meta = _parse_skill_meta(path)
        if not meta:
            continue
        if not meta.get("enabled", True):
            continue

        skill_id = path.stem
        if skill_id in existing:
            continue

        name = str(meta.get("name", skill_id))
        description = str(meta.get("description", ""))
        searchable = f"{name}。{description}" if description else name

        ep = Episode(
            id=f"skill_{skill_id}",
            content=searchable,
            type="skill",
            source="skill",
            skill_id=skill_id,
            importance=0.7,
        )
        store.add(ep)
        count += 1

    log.info("[SkillIndex] Indexed %d new skills from %s", count, skills_dir)
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
    store = EpisodeStore.for_employee(employee_name)
    global_skills_dir = get_marneo_dir() / "skills"
    count = index_skills_into_store(global_skills_dir, store)
    try:
        from marneo.project.workspace import get_employee_projects
        from marneo.core.paths import get_projects_dir
        for proj in get_employee_projects(employee_name):
            proj_skills_dir = get_projects_dir() / proj.name / "skills"
            count += index_skills_into_store(proj_skills_dir, store)
    except Exception:
        pass
    return count
