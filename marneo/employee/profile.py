# marneo/employee/profile.py
"""Employee profile — YAML-based, stored under ~/.marneo/employees/<name>/"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from marneo.core.paths import get_employees_dir

LEVEL_INTERN  = "实习生"
LEVEL_JUNIOR  = "初级员工"
LEVEL_MID     = "中级员工"
LEVEL_SENIOR  = "高级员工"
LEVEL_ORDER   = [LEVEL_INTERN, LEVEL_JUNIOR, LEVEL_MID, LEVEL_SENIOR]


@dataclass
class EmployeeProfile:
    name: str
    level: str = LEVEL_INTERN
    hired_at: str = ""
    personality: str = ""
    domains: str = ""
    style: str = ""
    level_conversations: int = 0
    level_skills: int = 0
    total_conversations: int = 0

    @property
    def is_intern(self) -> bool:
        return self.level == LEVEL_INTERN

    @property
    def directory(self) -> Path:
        d = get_employees_dir() / self.name
        d.mkdir(exist_ok=True)
        return d

    @property
    def soul_path(self) -> Path:
        return self.directory / "SOUL.md"

    @property
    def reports_dir(self) -> Path:
        d = self.directory / "reports"
        d.mkdir(exist_ok=True)
        return d


def list_employees() -> list[str]:
    d = get_employees_dir()
    return sorted(
        p.name for p in d.iterdir()
        if p.is_dir() and (p / "profile.yaml").exists()
    )


def load_profile(name: str) -> EmployeeProfile | None:
    path = get_employees_dir() / name / "profile.yaml"
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return EmployeeProfile(
            name=name,
            level=data.get("level", LEVEL_INTERN),
            hired_at=data.get("hired_at", ""),
            personality=data.get("personality", ""),
            domains=data.get("domains", ""),
            style=data.get("style", ""),
            level_conversations=int(data.get("level_conversations", 0)),
            level_skills=int(data.get("level_skills", 0)),
            total_conversations=int(data.get("total_conversations", 0)),
        )
    except Exception:
        return None


def save_profile(profile: EmployeeProfile) -> Path:
    profile.directory.mkdir(parents=True, exist_ok=True)
    path = profile.directory / "profile.yaml"
    data = {
        "name": profile.name,
        "level": profile.level,
        "hired_at": profile.hired_at,
        "personality": profile.personality,
        "domains": profile.domains,
        "style": profile.style,
        "level_conversations": profile.level_conversations,
        "level_skills": profile.level_skills,
        "total_conversations": profile.total_conversations,
    }
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


def create_employee(
    name: str,
    personality: str = "",
    domains: str = "",
    style: str = "",
) -> EmployeeProfile:
    hired_at = datetime.now(timezone.utc).isoformat()
    profile = EmployeeProfile(
        name=name, level=LEVEL_INTERN, hired_at=hired_at,
        personality=personality, domains=domains, style=style,
    )
    save_profile(profile)
    return profile


def increment_conversation(name: str) -> EmployeeProfile | None:
    profile = load_profile(name)
    if not profile:
        return None
    updated = replace(
        profile,
        level_conversations=profile.level_conversations + 1,
        total_conversations=profile.total_conversations + 1,
    )
    save_profile(updated)
    return updated
