# marneo/engine/provider.py
"""Resolve active LLM provider from config."""
from __future__ import annotations

import os
from dataclasses import dataclass

from marneo.core.config import load_config


@dataclass
class ResolvedProvider:
    api_key: str
    base_url: str
    model: str
    protocol: str
    provider_id: str


def resolve_provider() -> ResolvedProvider:
    """Return the configured provider. Raises ValueError if not configured."""
    cfg = load_config()
    if cfg.provider and cfg.provider.api_key:
        p = cfg.provider
        return ResolvedProvider(
            api_key=p.api_key,
            base_url=p.base_url,
            model=p.model,
            protocol=p.protocol,
            provider_id=p.id,
        )
    # Env var fallback
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if anthropic_key:
        return ResolvedProvider(
            api_key=anthropic_key,
            base_url="https://api.anthropic.com",
            model="claude-sonnet-4-6",
            protocol="anthropic-compatible",
            provider_id="anthropic",
        )
    if openai_key:
        return ResolvedProvider(
            api_key=openai_key,
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            protocol="openai-compatible",
            provider_id="openai",
        )
    raise ValueError("未配置 Provider。请先运行: marneo setup")
