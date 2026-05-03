# tests/engine/test_provider_failover.py
"""Tests for marneo.engine.provider failover logic."""
import time
from marneo.engine.provider import ProviderPool, ResolvedProvider


def _make_pool(*providers: ResolvedProvider) -> ProviderPool:
    pool = ProviderPool()
    pool._providers = list(providers)
    pool._states = {}
    pool._initialized = True
    from marneo.engine.provider import _ProviderState
    for p in providers:
        pool._states[p.provider_id] = _ProviderState()
    return pool


_P1 = ResolvedProvider("key1", "https://api1", "model1", "openai-compatible", "primary")
_P2 = ResolvedProvider("key2", "https://api2", "model2", "openai-compatible", "fallback")


class TestProviderPool:
    def test_resolve_returns_primary(self):
        pool = _make_pool(_P1, _P2)
        assert pool.resolve().provider_id == "primary"

    def test_success_resets_failures(self):
        pool = _make_pool(_P1, _P2)
        pool.report_failure("primary", "server")
        pool.report_failure("primary", "server")
        pool.report_success("primary")
        assert pool._states["primary"].consecutive_failures == 0

    def test_auth_error_switches_provider(self):
        pool = _make_pool(_P1, _P2)
        pool.report_failure("primary", "auth")
        # Should resolve to fallback now
        assert pool.resolve().provider_id == "fallback"

    def test_rate_limit_applies_backoff(self):
        pool = _make_pool(_P1, _P2)
        pool.report_failure("primary", "rate_limit")
        state = pool._states["primary"]
        assert state.cooldown_until > time.time()

    def test_three_failures_triggers_switch(self):
        pool = _make_pool(_P1, _P2)
        pool.report_failure("primary", "server")
        pool.report_failure("primary", "server")
        pool.report_failure("primary", "server")
        # After 3 failures, should switch
        assert pool.resolve().provider_id == "fallback"

    def test_single_provider_survives(self):
        pool = _make_pool(_P1)
        pool.report_failure("primary", "rate_limit")
        # Should still return primary (only option)
        result = pool.resolve()
        assert result.provider_id == "primary"


def test_local_only_mode_ignores_remote_env_fallbacks(monkeypatch):
    from marneo.core.paths import get_config_path
    from marneo.engine.provider import ProviderPool

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-env")
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("privacy:\n  local_only: true\n", encoding="utf-8")

    pool = ProviderPool()

    try:
        pool.resolve()
    except ValueError as exc:
        assert "local" in str(exc).lower() or "本地" in str(exc)
    else:
        raise AssertionError("local-only mode must not use remote env provider fallbacks")
