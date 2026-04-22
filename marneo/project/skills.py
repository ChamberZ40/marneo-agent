# marneo/project/skills.py
"""Skill management — global and project-scoped skills."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from marneo.core.paths import get_marneo_dir, get_projects_dir


@dataclass
class Skill:
    id: str
    name: str
    description: str = ""
    scope: str = "global"  # "global" or "project:<name>"
    enabled: bool = True
    content: str = ""
    source_path: Path | None = None


def _global_skills_dir() -> Path:
    d = get_marneo_dir() / "skills"
    d.mkdir(exist_ok=True)
    return d


def _parse_skill_file(path: Path) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
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

    skill_id = path.stem
    return Skill(
        id=skill_id,
        name=meta.get("name", skill_id),
        description=meta.get("description", ""),
        scope=meta.get("scope", "global"),
        enabled=bool(meta.get("enabled", True)),
        content=body,
        source_path=path,
    )


def list_skills(include_project: str | None = None) -> list[Skill]:
    """List enabled skills (global + optionally project-specific)."""
    skills: list[Skill] = []
    for path in sorted(_global_skills_dir().glob("*.md")):
        skill = _parse_skill_file(path)
        if skill and skill.enabled:
            skills.append(skill)
    if include_project:
        proj_dir = get_projects_dir() / include_project / "skills"
        if proj_dir.exists():
            for path in sorted(proj_dir.glob("*.md")):
                skill = _parse_skill_file(path)
                if skill and skill.enabled:
                    skills.append(skill)
    return skills


def save_skill(skill: Skill) -> Path:
    """Save skill file. Returns the file path."""
    if skill.scope.startswith("project:"):
        proj_name = skill.scope[len("project:"):]
        skills_dir = get_projects_dir() / proj_name / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
    else:
        skills_dir = _global_skills_dir()

    path = skills_dir / f"{skill.id}.md"
    meta = {
        "name": skill.name,
        "description": skill.description,
        "scope": skill.scope,
        "enabled": skill.enabled,
    }
    content = f"---\n{yaml.dump(meta, allow_unicode=True)}---\n\n{skill.content}"
    path.write_text(content, encoding="utf-8")
    return path


def get_skills_context(employee_name: str) -> str:
    """Build skill context string for system prompt injection."""
    from marneo.project.workspace import get_employee_projects
    projects = get_employee_projects(employee_name)

    all_skills: list[Skill] = list_skills()
    for proj in projects:
        all_skills.extend(list_skills(include_project=proj.name))

    if not all_skills:
        return ""

    lines = ["# 可用技能\n"]
    for skill in all_skills:
        if skill.content.strip():
            lines.append(f"## {skill.name}\n{skill.description}\n\n{skill.content}\n")
    return "\n".join(lines) if len(lines) > 1 else ""
