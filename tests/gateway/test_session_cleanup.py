# tests/gateway/test_session_cleanup.py
"""Tests for periodic session eviction."""
import pytest

from marneo.gateway.session import SessionStore


@pytest.mark.asyncio
async def test_session_eviction():
    """Expired sessions are evicted by _evict()."""
    store = SessionStore()
    engine, lock = await store.get_or_create("test", "c1")
    assert store.active_count == 1

    # Manually expire by setting _last to epoch-like value
    key = "test:c1"
    store._sessions[key]._last = 0  # epoch = expired
    store._evict()
    assert store.active_count == 0


@pytest.mark.asyncio
async def test_active_sessions_not_evicted():
    """Active (non-expired) sessions survive eviction."""
    store = SessionStore()
    await store.get_or_create("test", "c1")
    await store.get_or_create("test", "c2")
    assert store.active_count == 2

    # Only expire one
    store._sessions["test:c1"]._last = 0
    store._evict()
    assert store.active_count == 1
    assert "test:c2" in store._sessions
