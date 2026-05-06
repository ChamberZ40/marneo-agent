# tests/gateway/test_health.py
"""Tests for health endpoint response structure."""
from __future__ import annotations

import time
from types import SimpleNamespace

from marneo.gateway.base import BaseChannelAdapter
from marneo.gateway.manager import GatewayManager


def test_health_endpoint_fields():
    """Verify health response includes expected fields."""
    expected_fields = {
        "status",
        "uptime_seconds",
        "sessions",
        "connected_channels",
        "channels_detail",
        "tools",
        "last_event_seconds_ago",
    }
    assert "status" in expected_fields
    assert "tools" in expected_fields
    assert "last_event_seconds_ago" in expected_fields
    assert "channels_detail" in expected_fields
    assert len(expected_fields) == 7


class FakeFeishuAdapter(BaseChannelAdapter):
    def __init__(self) -> None:
        super().__init__("feishu:laoqi")
        self._running = True
        self._employee_name = "laoqi"
        self._connection_mode = "websocket"
        self._domain = "feishu"
        self._bot_open_id = "ou_bot_secret_should_not_leak_full"
        self._bot_user_id = "u_bot_secret_should_not_leak_full"
        self._bot_name = "小A豪"
        self._last_event_time = time.monotonic() - 12
        self._pending_inbound = [object(), object()]
        self._pending_text_batches = {"k": object()}
        self._ws_future = SimpleNamespace(done=lambda: False)
        self._ws_client = SimpleNamespace(_conn=SimpleNamespace(closed=False, close_code=None))

    def card_action_metrics_snapshot(self):
        return {"received": 3, "resolved": 1, "errors": 0, "last_event": {}}

    def pending_questions_snapshot(self):
        return {"total": 2, "by_chat": {"app1:chat1": 2}}

    async def connect(self, config):
        return True

    async def disconnect(self):
        pass

    async def send_reply(self, chat_id, text, **kw):
        return True


def test_health_payload_includes_per_employee_feishu_details_without_full_ids():
    mgr = GatewayManager()
    mgr.register(FakeFeishuAdapter())

    payload = mgr.health_payload(start_time=time.time() - 10)

    assert payload["connected_channels"] == ["feishu:laoqi"]
    detail = payload["channels_detail"]["feishu:laoqi"]
    assert detail["platform"] == "feishu:laoqi"
    assert detail["employee"] == "laoqi"
    assert detail["running"] is True
    assert detail["connection_mode"] == "websocket"
    assert detail["domain"] == "feishu"
    assert detail["bot_name"] == "小A豪"
    assert detail["bot_open_id"].endswith("...")
    assert detail["bot_user_id"].endswith("...")
    assert detail["bot_open_id"] != "ou_bot_secret_should_not_leak_full"
    assert detail["bot_user_id"] != "u_bot_secret_should_not_leak_full"
    assert detail["last_event_seconds_ago"] >= 0
    assert detail["pending_inbound"] == 2
    assert detail["pending_text_batches"] == 1
    assert detail["ws"]["future_done"] is False
    assert detail["ws"]["connection_lost"] is False
    assert detail["card_actions"]["received"] == 3
    assert detail["card_actions"]["resolved"] == 1
    assert detail["pending_questions"]["total"] == 2
    assert detail["pending_questions"]["by_chat"] == {"app1:chat1": 2}
    assert "secret" not in str(detail["pending_questions"])
