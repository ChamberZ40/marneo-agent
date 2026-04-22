# marneo/gateway/config.py
from __future__ import annotations
from typing import Any
import yaml
from marneo.core.paths import get_config_path


def load_channel_configs() -> dict[str, dict[str, Any]]:
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data.get("channels", {})
    except Exception:
        return {}


def save_channel_config(platform: str, config: dict[str, Any]) -> None:
    path = get_config_path()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    if "channels" not in data:
        data["channels"] = {}
    data["channels"][platform] = config
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")


def get_channel_config(platform: str) -> dict[str, Any] | None:
    return load_channel_configs().get(platform)
