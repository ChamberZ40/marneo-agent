# marneo/engine/provider.py
"""Resolve active LLM provider from config with failover support.

Hermes-agent pattern: primary + fallback providers. On rate_limit → wait+retry,
on auth_error → switch provider, on server_error → degrade to fallback model.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from marneo.core.config import load_config

log = logging.getLogger(__name__)


@dataclass
class ResolvedProvider:
    api_key: str
    base_url: str
    model: str
    protocol: str
    provider_id: str


@dataclass
class _ProviderState:
    """Track provider health for failover decisions."""
    consecutive_failures: int = 0
    last_failure_time: float = 0
    cooldown_until: float = 0  # don't use until this timestamp


class ProviderPool:
    """Manages primary + fallback providers with automatic failover.

    Failover strategy (hermes pattern):
    - rate_limit (429)  → exponential backoff on same provider
    - auth_error (401)  → mark provider dead, switch to next
    - server_error (5xx) → try fallback provider
    """

    _BACKOFF_BASE = 2.0
    _BACKOFF_MAX = 60.0
    _FAILURE_COOLDOWN = 300  # 5 min cooldown after 3 failures

    def __init__(self) -> None:
        self._providers: list[ResolvedProvider] = []
        self._states: dict[str, _ProviderState] = {}
        self._current_idx: int = 0
        self._initialized = False

    def _init_providers(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        # Primary from config
        cfg = load_config()
        if cfg.provider and cfg.provider.api_key:
            p = cfg.provider
            self._providers.append(ResolvedProvider(
                api_key=p.api_key, base_url=p.base_url,
                model=p.model, protocol=p.protocol, provider_id=p.id,
            ))

        # Fallbacks from config
        fallbacks = getattr(cfg, "fallback_providers", None) or []
        for fb in fallbacks:
            if isinstance(fb, dict) and fb.get("api_key"):
                self._providers.append(ResolvedProvider(
                    api_key=fb["api_key"],
                    base_url=fb.get("base_url", ""),
                    model=fb.get("model", ""),
                    protocol=fb.get("protocol", "openai-compatible"),
                    provider_id=fb.get("id", f"fallback-{len(self._providers)}"),
                ))

        # Local-only/private mode must never silently fall back to remote env providers.
        local_only = cfg.privacy.local_only
        if local_only:
            from marneo.core.config import is_local_provider_url
            self._providers = [p for p in self._providers if is_local_provider_url(p.base_url)]

        # Env var fallbacks (if nothing from config). Disabled in local-only mode.
        if not self._providers and not local_only:
            anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
            openai_key = os.environ.get("OPENAI_API_KEY", "")
            if anthropic_key:
                self._providers.append(ResolvedProvider(
                    api_key=anthropic_key,
                    base_url="https://api.anthropic.com",
                    model="claude-sonnet-4-6",
                    protocol="anthropic-compatible",
                    provider_id="anthropic",
                ))
            if openai_key:
                self._providers.append(ResolvedProvider(
                    api_key=openai_key,
                    base_url="https://api.openai.com/v1",
                    model="gpt-4o",
                    protocol="openai-compatible",
                    provider_id="openai",
                ))

        for p in self._providers:
            self._states[p.provider_id] = _ProviderState()

    def resolve(self) -> ResolvedProvider:
        """Return the best available provider. Raises ValueError if none available."""
        self._init_providers()
        if not self._providers:
            cfg = load_config()
            if cfg.privacy.local_only:
                raise ValueError("本地-only/private 模式需要配置本地 LLM Provider（例如 Ollama / localhost OpenAI-compatible）。请运行: marneo setup")
            raise ValueError("未配置 Provider。请先运行: marneo setup")

        now = time.time()
        # Try from current index, cycling through all providers
        for offset in range(len(self._providers)):
            idx = (self._current_idx + offset) % len(self._providers)
            p = self._providers[idx]
            state = self._states[p.provider_id]
            if state.cooldown_until > now:
                continue  # provider on cooldown
            self._current_idx = idx
            return p

        # All on cooldown — use the one with earliest cooldown expiry
        earliest = min(self._providers,
                       key=lambda p: self._states[p.provider_id].cooldown_until)
        return earliest

    def report_success(self, provider_id: str) -> None:
        """Reset failure state on success."""
        state = self._states.get(provider_id)
        if state:
            state.consecutive_failures = 0

    def report_failure(self, provider_id: str, error_type: str = "unknown") -> None:
        """Record failure and apply backoff/cooldown.

        error_type: "rate_limit" | "auth" | "server" | "unknown"
        """
        state = self._states.get(provider_id)
        if not state:
            return
        state.consecutive_failures += 1
        state.last_failure_time = time.time()

        if error_type == "auth":
            # Auth errors: long cooldown, switch immediately
            state.cooldown_until = time.time() + self._FAILURE_COOLDOWN
            self._current_idx = (self._current_idx + 1) % max(len(self._providers), 1)
            log.warning("[Provider] %s auth error, switching to next", provider_id)
        elif error_type == "rate_limit":
            # Rate limit: exponential backoff
            delay = min(self._BACKOFF_BASE ** state.consecutive_failures, self._BACKOFF_MAX)
            state.cooldown_until = time.time() + delay
            log.info("[Provider] %s rate limited, backoff %.1fs", provider_id, delay)
        elif state.consecutive_failures >= 3:
            # 3+ failures: cooldown and switch
            state.cooldown_until = time.time() + self._FAILURE_COOLDOWN
            self._current_idx = (self._current_idx + 1) % max(len(self._providers), 1)
            log.warning("[Provider] %s failed %d times, switching to next",
                        provider_id, state.consecutive_failures)


# Module-level singleton
_pool = ProviderPool()


def resolve_provider() -> ResolvedProvider:
    """Return the configured provider (with failover). Raises ValueError if not configured."""
    return _pool.resolve()


def report_provider_success(provider_id: str) -> None:
    _pool.report_success(provider_id)


def report_provider_failure(provider_id: str, error_type: str = "unknown") -> None:
    _pool.report_failure(provider_id, error_type)
