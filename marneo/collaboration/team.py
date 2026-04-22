# marneo/collaboration/team.py
"""Team configuration for multi-employee collaboration.

Stored in project.yaml under 'team:' key.

Example project.yaml:
  team:
    coordinator: GAI
    team_chat_id: oc_xxx       # Feishu group chat ID
    members:
      - employee: GAI
        role: 协调者
      - employee: ARIA
        role: 数据分析专员
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

from marneo.core.paths import get_projects_dir


@dataclass
class TeamMember:
    employee: str
    role: str = ""


@dataclass
class TeamConfig:
    project_name: str
    coordinator: str = ""
    team_chat_id: str = ""
    members: list[TeamMember] = field(default_factory=list)

    @property
    def member_names(self) -> list[str]:
        return [m.employee for m in self.members]

    @property
    def specialists(self) -> list[TeamMember]:
        return [m for m in self.members if m.employee != self.coordinator]

    def is_configured(self) -> bool:
        return bool(self.coordinator and len(self.members) >= 2)


def load_team_config(project_name: str) -> TeamConfig | None:
    """Load team config from project.yaml."""
    path = get_projects_dir() / project_name / "project.yaml"
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        team_data = data.get("team", {})
        if not team_data:
            return TeamConfig(project_name=project_name)
        members = [
            TeamMember(employee=m["employee"], role=m.get("role", ""))
            for m in team_data.get("members", [])
            if isinstance(m, dict) and m.get("employee")
        ]
        return TeamConfig(
            project_name=project_name,
            coordinator=team_data.get("coordinator", ""),
            team_chat_id=team_data.get("team_chat_id", ""),
            members=members,
        )
    except Exception:
        return None


def save_team_config(config: TeamConfig) -> None:
    """Save team config into project.yaml."""
    path = get_projects_dir() / config.project_name / "project.yaml"
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    data["team"] = {
        "coordinator": config.coordinator,
        "team_chat_id": config.team_chat_id,
        "members": [{"employee": m.employee, "role": m.role} for m in config.members],
    }
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
