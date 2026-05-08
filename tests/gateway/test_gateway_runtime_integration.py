"""Tests for gateway runtime status integration with GatewayManager."""
from __future__ import annotations

import asyncio

import pytest

from marneo.gateway import status as gateway_status
from marneo.gateway.base import BaseChannelAdapter
from marneo.gateway.manager import GatewayManager


class RuntimeStatusAdapter(BaseChannelAdapter):
    def __init__(self) -> None:
        super().__init__("feishu:runtime")
        self._employee_name = "runtime"
        self._connection_mode = "websocket"
        self._domain = "feishu"
        self._bot_open_id = "ou_runtime_secret_should_not_leak"
        self._bot_user_id = "u_runtime_secret_should_not_leak"
        self._bot_name = "RuntimeBot"

    async def connect(self, config):
        self._running = True
        return True

    async def disconnect(self):
        self._running = False

    async def send_reply(self, chat_id, text, **kw):
        return True


@pytest.mark.asyncio
async def test_run_forever_writes_running_state_and_channel_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("marneo.gateway.config.load_channel_configs", lambda: {})
    monkeypatch.setattr("marneo.employee.feishu_config.list_configured_employees", lambda: [])

    manager = GatewayManager()
    manager.register(RuntimeStatusAdapter())

    async def stop_soon():
        await asyncio.sleep(0.02)
        manager.request_stop()

    await asyncio.gather(manager.run_forever(start_health=False), stop_soon())

    payload = gateway_status.read_runtime_status()
    assert payload is not None
    assert payload["gateway_state"] == "stopped"
    detail = payload["channels"]["feishu:runtime"]
    assert detail["state"] == "disconnected"
    assert detail["employee"] == "runtime"
    assert detail["connection_mode"] == "websocket"
    assert "ou_runtime_secret_should_not_leak" not in str(payload)


def test_write_runtime_status_and_update_channel_status_redact_nested_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    gateway_status.write_runtime_status(
        gateway_state="running",
        channels={
            "feishu:x": {
                "state": "failed",
                "error": "app_secret=supersecretvalue123456 access_token=tokenvalue123456789",
            }
        },
    )
    gateway_status.update_channel_status(
        "feishu:x",
        {
            "debug": {
                "Authorization": "Authorization: Bearer verylongbearertoken123456789",
                "ticket": "ticket=ws-ticket-secret-value",
            }
        },
    )

    raw = gateway_status.get_runtime_status_path().read_text(encoding="utf-8")
    assert "supersecretvalue123456" not in raw
    assert "tokenvalue123456789" not in raw
    assert "verylongbearertoken123456789" not in raw
    assert "ws-ticket-secret-value" not in raw
    assert "***" in raw
