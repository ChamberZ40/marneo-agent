# marneo/core/config.py
"""YAML config management for ~/.marneo/config.yaml."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from marneo.core.paths import get_config_path

log = logging.getLogger(__name__)

VALID_PROTOCOLS = {"anthropic-compatible", "openai-compatible"}


@dataclass
class ProviderConfig:
    id: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    protocol: str = "openai-compatible"


@dataclass
class ContextBudgetConfig:
    system_prompt_max: int = 4000
    core_memory_max: int = 1000
    working_memory_turns: int = 20
    episodic_inject_max: int = 1500
    tool_result_max: int = 50_000


@dataclass
class MarneoConfig:
    provider: ProviderConfig | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    context_budget: ContextBudgetConfig = field(default_factory=ContextBudgetConfig)


def _resolve_secret(value: str) -> str:
    """Expand ${ENV_VAR} references."""
    if not value:
        return value
    m = re.fullmatch(r"\$\{?(\w+)\}?", value.strip())
    if m:
        return os.environ.get(m.group(1), value)
    return value


def load_config() -> MarneoConfig:
    """Load config from ~/.marneo/config.yaml. Returns empty config if missing."""
    path = get_config_path()
    if not path.exists():
        return MarneoConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.warning("Failed to load config: %s", e)
        return MarneoConfig()

    provider = None
    p = raw.get("provider", {})
    if p and p.get("base_url"):
        provider = ProviderConfig(
            id=str(p.get("id", "default")),
            base_url=str(p.get("base_url", "")),
            api_key=_resolve_secret(str(p.get("api_key", ""))),
            model=str(p.get("model", "")),
            protocol=str(p.get("protocol", "openai-compatible")),
        )

    config = MarneoConfig(provider=provider, raw=raw)

    raw_budget = raw.get("context_budget", {}) or {}
    if isinstance(raw_budget, dict) and raw_budget:
        config.context_budget = ContextBudgetConfig(
            system_prompt_max=int(raw_budget.get("system_prompt_max", 4000)),
            core_memory_max=int(raw_budget.get("core_memory_max", 1000)),
            working_memory_turns=int(raw_budget.get("working_memory_turns", 20)),
            episodic_inject_max=int(raw_budget.get("episodic_inject_max", 1500)),
            tool_result_max=int(raw_budget.get("tool_result_max", 50_000)),
        )

    return config


def save_config(provider: ProviderConfig) -> Path:
    """Save provider config to ~/.marneo/config.yaml. Returns config path."""
    path = get_config_path()
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass

    existing["provider"] = {
        "id": provider.id,
        "base_url": provider.base_url,
        "api_key": provider.api_key,
        "model": provider.model,
        "protocol": provider.protocol,
    }
    path.write_text(yaml.dump(existing, allow_unicode=True), encoding="utf-8")
    return path


def is_configured() -> bool:
    """Return True if a provider is configured."""
    cfg = load_config()
    return cfg.provider is not None and bool(cfg.provider.api_key)
