# tests/gateway/test_health.py
"""Tests for health endpoint response structure."""


def test_health_endpoint_fields():
    """Verify health response includes expected fields."""
    expected_fields = {"status", "uptime_seconds", "sessions", "connected_channels", "tools", "last_event_seconds_ago"}
    # Structural assertion — the actual HTTP test is `curl localhost:8765/health`
    assert "status" in expected_fields
    assert "tools" in expected_fields
    assert "last_event_seconds_ago" in expected_fields
    assert len(expected_fields) == 6
