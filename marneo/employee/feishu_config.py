# marneo/employee/feishu_config.py
"""Per-employee Feishu Bot configuration.

Each employee can have their own Feishu App (Bot).
Config stored at: ~/.marneo/employees/<name>/feishu.yaml

Fields:
  app_id      - Feishu App ID
  app_secret  - Feishu App Secret
  domain      - "feishu" | "lark", default "feishu"
  bot_open_id - Bot's own open_id (fetched during probe)
  team_chat_id- Feishu group chat ID for team collaboration (optional)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from marneo.core.paths import get_employees_dir


@dataclass
class EmployeeFeishuConfig:
    employee_name: str
    app_id: str
    app_secret: str
    domain: str = "feishu"
    bot_open_id: str = ""
    team_chat_id: str = ""

    @property
    def is_complete(self) -> bool:
        return bool(self.app_id and self.app_secret)


def _config_path(employee_name: str) -> Path:
    return get_employees_dir() / employee_name / "feishu.yaml"


def has_feishu_config(employee_name: str) -> bool:
    """Return True if employee has Feishu Bot configured."""
    return _config_path(employee_name).exists()


def load_feishu_config(employee_name: str) -> EmployeeFeishuConfig | None:
    """Load employee Feishu config. Returns None if not configured."""
    path = _config_path(employee_name)
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return EmployeeFeishuConfig(
            employee_name=employee_name,
            app_id=data.get("app_id", ""),
            app_secret=data.get("app_secret", ""),
            domain=data.get("domain", "feishu"),
            bot_open_id=data.get("bot_open_id", ""),
            team_chat_id=data.get("team_chat_id", ""),
        )
    except Exception:
        return None


def save_feishu_config(config: EmployeeFeishuConfig) -> Path:
    """Save employee Feishu config. Returns config file path."""
    path = _config_path(config.employee_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "app_id": config.app_id,
        "app_secret": config.app_secret,
        "domain": config.domain,
        "bot_open_id": config.bot_open_id,
        "team_chat_id": config.team_chat_id,
    }
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


def list_configured_employees() -> list[str]:
    """Return names of employees with Feishu Bot configured."""
    from marneo.employee.profile import list_employees
    return [name for name in list_employees() if has_feishu_config(name)]
