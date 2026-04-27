# tests/gateway/test_feishu_watchdog.py
"""Tests for Feishu WS watchdog — stale-connection detection."""
import asyncio
import time
from unittest.mock import MagicMock

import pytest

from marneo.gateway.adapters.feishu import FeishuChannelAdapter


@pytest.mark.asyncio
async def test_watchdog_detects_stale_connection():
    """Watchdog fires when no events received for threshold period."""
    adapter = FeishuChannelAdapter(MagicMock(), employee_name="test")
    adapter._last_event_time = time.monotonic() - 400  # 6+ minutes ago
    adapter._loop = asyncio.get_running_loop()
    assert adapter._should_restart_ws()


@pytest.mark.asyncio
async def test_watchdog_does_not_fire_when_active():
    """Watchdog does not fire when events are recent."""
    adapter = FeishuChannelAdapter(MagicMock(), employee_name="test")
    adapter._last_event_time = time.monotonic()  # just now
    assert not adapter._should_restart_ws()


@pytest.mark.asyncio
async def test_watchdog_does_not_fire_on_startup():
    """Watchdog does not fire when no events have been received yet (startup)."""
    adapter = FeishuChannelAdapter(MagicMock(), employee_name="test")
    # _last_event_time defaults to 0 — never received
    assert adapter._last_event_time == 0
    assert not adapter._should_restart_ws()


@pytest.mark.asyncio
async def test_watchdog_custom_threshold():
    """Watchdog respects custom threshold parameter."""
    adapter = FeishuChannelAdapter(MagicMock(), employee_name="test")
    adapter._last_event_time = time.monotonic() - 120  # 2 minutes ago
    assert not adapter._should_restart_ws(threshold=300)  # 5 min threshold
    assert adapter._should_restart_ws(threshold=60)  # 1 min threshold
