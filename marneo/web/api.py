"""JSON payload builders for the local web console."""
from __future__ import annotations

import re
from typing import Any

from marneo import __version__
from marneo.core.config import is_local_provider_url, load_config

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)(app_secret|client_secret|api_key|access_token|refresh_token|access_key|ticket)(\s*[:=]\s*)([^\s,'\"]+)"),
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,'\"]+)"),
]


def redact_text(value: str) -> str:
    """Redact likely secrets in user-facing web payload strings."""
    result = value
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.lower().startswith("(?i)(authorization"):
            result = pattern.sub(r"\1[redacted]", result)
        elif "(\\s*[:=]" in pattern.pattern:
            result = pattern.sub(r"\1\2[redacted]", result)
        else:
            result = pattern.sub("[redacted]", result)
    return result


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if value.startswith("${") and value.endswith("}"):
        return value
    return "[redacted]"


def build_status_payload() -> dict[str, Any]:
    """Return local status without exposing raw credentials or config YAML."""
    from marneo.core.paths import get_config_path, get_marneo_dir
    from marneo.employee.profile import list_employees
    from marneo.gateway.config import load_channel_configs
    from marneo.cli.gateway_cmd import _read_pid

    cfg = load_config()
    provider = cfg.provider
    channels = load_channel_configs()
    enabled_channels = [name for name, data in channels.items() if isinstance(data, dict) and data.get("enabled")]
    pid = _read_pid()

    return {
        "app": {"name": "marneo", "version": __version__},
        "server": {"bind_default": "127.0.0.1", "type": "local-console"},
        "paths": {
            "home": str(get_marneo_dir()),
            "config": str(get_config_path()),
        },
        "provider": {
            "configured": bool(provider and provider.api_key),
            "id": provider.id if provider else None,
            "model": provider.model if provider else None,
            "base_url": provider.base_url if provider else None,
            "local": is_local_provider_url(provider.base_url) if provider else False,
            "api_key": _mask_secret(provider.api_key) if provider else "",
        },
        "privacy": {"local_only": cfg.privacy.local_only},
        "employees": {"count": len(list_employees())},
        "gateway": {
            "running": pid is not None,
            "pid": pid,
            "enabled_channels": enabled_channels,
        },
    }


def build_employees_payload() -> dict[str, Any]:
    """Return employee cards for the web console."""
    from marneo.employee.profile import list_employees, load_profile
    from marneo.project.workspace import get_employee_projects

    employees: list[dict[str, Any]] = []
    for name in list_employees():
        profile = load_profile(name)
        if not profile:
            continue
        employees.append({
            "name": profile.name,
            "level": profile.level,
            "hired_at": profile.hired_at,
            "personality": profile.personality,
            "domains": profile.domains,
            "style": profile.style,
            "level_conversations": profile.level_conversations,
            "total_conversations": profile.total_conversations,
            "projects": [project.name for project in get_employee_projects(name)],
        })
    return {"employees": employees}


def build_employee_payload(name: str) -> dict[str, Any] | None:
    """Return one employee or None if missing."""
    payload = build_employees_payload()
    for employee in payload["employees"]:
        if employee["name"] == name:
            return employee
    return None


def build_projects_payload() -> dict[str, Any]:
    """Return project cards for the web console."""
    from marneo.project.workspace import list_projects, load_project

    projects: list[dict[str, Any]] = []
    for name in list_projects():
        project = load_project(name)
        if not project:
            continue
        projects.append({
            "name": project.name,
            "description": project.description,
            "goals": project.goals,
            "kpis": [{"name": kpi.name, "target": kpi.target, "unit": kpi.unit} for kpi in project.kpis],
            "tools": project.tools,
            "created_at": project.created_at,
            "assigned_employees": project.assigned_employees,
        })
    return {"projects": projects}


def build_gateway_logs_payload(lines: int = 200) -> dict[str, Any]:
    """Return redacted gateway log tail."""
    from marneo.cli.gateway_cmd import _log_file

    safe_lines = max(1, min(int(lines), 1000))
    path = _log_file()
    if not path.exists():
        return {"lines": [], "path": str(path)}
    raw_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-safe_lines:]
    return {"lines": [redact_text(line) for line in raw_lines], "path": str(path)}
