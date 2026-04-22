# marneo/project/workspace.py
"""Project workspace — YAML-based, stored under ~/.marneo/projects/<name>/"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from marneo.core.paths import get_projects_dir


@dataclass
class KPI:
    name: str
    target: str = ""
    unit: str = ""


@dataclass
class ProjectWorkspace:
    name: str
    description: str = ""
    goals: list[str] = field(default_factory=list)
    kpis: list[KPI] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    created_at: str = ""
    assigned_employees: list[str] = field(default_factory=list)

    @property
    def directory(self) -> Path:
        d = get_projects_dir() / self.name
        d.mkdir(exist_ok=True)
        return d

    @property
    def agent_path(self) -> Path:
        return self.directory / "AGENT.md"

    @property
    def skills_dir(self) -> Path:
        d = self.directory / "skills"
        d.mkdir(exist_ok=True)
        return d


def list_projects() -> list[str]:
    d = get_projects_dir()
    return sorted(
        p.name for p in d.iterdir()
        if p.is_dir() and (p / "project.yaml").exists()
    )


def load_project(name: str) -> ProjectWorkspace | None:
    path = get_projects_dir() / name / "project.yaml"
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        kpis = [
            KPI(name=k.get("name", ""), target=str(k.get("target", "")), unit=k.get("unit", ""))
            for k in data.get("kpis", [])
            if isinstance(k, dict)
        ]
        return ProjectWorkspace(
            name=name,
            description=data.get("description", ""),
            goals=data.get("goals", []),
            kpis=kpis,
            tools=data.get("tools", []),
            created_at=data.get("created_at", ""),
            assigned_employees=data.get("assigned_employees", []),
        )
    except Exception:
        return None


def save_project(project: ProjectWorkspace) -> Path:
    project.directory.mkdir(parents=True, exist_ok=True)
    path = project.directory / "project.yaml"
    data: dict[str, Any] = {
        "name": project.name,
        "description": project.description,
        "goals": project.goals,
        "kpis": [{"name": k.name, "target": k.target, "unit": k.unit} for k in project.kpis],
        "tools": project.tools,
        "created_at": project.created_at,
        "assigned_employees": project.assigned_employees,
    }
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


def create_project(
    name: str,
    description: str = "",
    goals: list[str] | None = None,
) -> ProjectWorkspace:
    project = ProjectWorkspace(
        name=name,
        description=description,
        goals=goals or [],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    save_project(project)
    return project


def assign_employee(project_name: str, employee_name: str) -> bool:
    project = load_project(project_name)
    if not project:
        return False
    if employee_name not in project.assigned_employees:
        project.assigned_employees.append(employee_name)
        save_project(project)
    return True


def get_employee_projects(employee_name: str) -> list[ProjectWorkspace]:
    result: list[ProjectWorkspace] = []
    for name in list_projects():
        p = load_project(name)
        if p and employee_name in p.assigned_employees:
            result.append(p)
    return result
