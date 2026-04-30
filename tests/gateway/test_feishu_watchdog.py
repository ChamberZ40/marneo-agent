# tests/gateway/test_feishu_watchdog.py
"""Tests for Feishu WS watchdog — stale-connection detection."""
import asyncio
import logging
import os
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
async def test_watchdog_detects_sdk_receive_loop_disconnect_before_any_event():
    """Watchdog restarts when lark-oapi receive loop dies before any user event.

    lark-oapi Client.start() blocks forever in _select(), so the executor future
    can remain alive even after _receive_message_loop calls _disconnect() and
    clears client._conn. This is the production failure where health still says
    connected but Feishu messages/card actions no longer arrive.
    """
    adapter = FeishuChannelAdapter(MagicMock(), employee_name="test")
    adapter._ws_client = SimpleNamespace(_conn=None)
    adapter._ws_started_time = time.monotonic() - 120
    adapter._last_event_time = 0

    assert adapter._ws_connection_lost()


@pytest.mark.asyncio
async def test_watchdog_ignores_initial_ws_connection_window():
    """A client with no _conn is allowed briefly while _connect() is still running."""
    adapter = FeishuChannelAdapter(MagicMock(), employee_name="test")
    adapter._ws_client = SimpleNamespace(_conn=None)
    adapter._ws_started_time = time.monotonic()

    assert not adapter._ws_connection_lost(startup_grace=30)


@pytest.mark.asyncio
async def test_watchdog_custom_threshold():
    """Watchdog respects custom threshold parameter."""
    adapter = FeishuChannelAdapter(MagicMock(), employee_name="test")
    adapter._last_event_time = time.monotonic() - 120  # 2 minutes ago
    assert not adapter._should_restart_ws(threshold=300)  # 5 min threshold
    assert adapter._should_restart_ws(threshold=60)  # 1 min threshold


@pytest.mark.asyncio
async def test_kill_ws_swallows_cancelled_executor_future():
    """Killing WS should not leak asyncio.CancelledError from the executor future."""
    adapter = FeishuChannelAdapter(MagicMock(), employee_name="test")
    adapter._ws_future = asyncio.get_running_loop().create_future()

    await adapter._kill_ws()

    assert adapter._ws_future is None


@pytest.mark.asyncio
async def test_disconnect_logs_once(caplog):
    """Disconnect should emit one lifecycle log, not duplicate lines."""
    adapter = FeishuChannelAdapter(MagicMock(), employee_name="test")

    with caplog.at_level(logging.INFO, logger="marneo.gateway.adapters.feishu"):
        await adapter.disconnect()

    messages = [r.getMessage() for r in caplog.records]
    assert messages.count("[Feishu] Disconnected (employee=test)") == 1


def test_card_monkey_patch_is_disabled_by_default_in_fresh_import():
    """Importing the adapter must not globally patch lark-oapi unless explicitly enabled."""
    env = os.environ.copy()
    env.pop("MARNEO_FEISHU_ENABLE_CARD_WS_PATCH", None)
    code = textwrap.dedent(
        """
        import inspect
        import marneo.gateway.adapters.feishu  # noqa: F401
        from lark_oapi.ws import Client
        source = inspect.getsource(Client._handle_data_frame)
        print('PATCHED=' + str('_fixed_handle_data_frame' in source))
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "PATCHED=False" in result.stdout


@pytest.mark.asyncio
async def test_start_websocket_keeps_card_monkey_patch_disabled_by_default():
    """Starting the Feishu WebSocket must not enable the risky CARD monkey patch by default."""
    import marneo.gateway.adapters.feishu as feishu_mod

    adapter = FeishuChannelAdapter(MagicMock(), employee_name="test")
    adapter._app_id = "app1"
    adapter._app_secret = "secret1"

    def _fake_run_ws(*args):
        return None

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MARNEO_FEISHU_ENABLE_CARD_WS_PATCH", None)
        with patch.object(feishu_mod, "_patch_lark_oapi_card_handling") as mock_patch:
            with patch.object(feishu_mod, "_run_feishu_ws_client", side_effect=_fake_run_ws):
                await adapter._start_websocket()
                await adapter._ws_future

    mock_patch.assert_not_called()


@pytest.mark.asyncio
async def test_start_websocket_enables_card_monkey_patch_when_explicitly_requested():
    """CARD monkey patch remains available behind an explicit runtime opt-in."""
    import marneo.gateway.adapters.feishu as feishu_mod

    adapter = FeishuChannelAdapter(MagicMock(), employee_name="test")
    adapter._app_id = "app1"
    adapter._app_secret = "secret1"

    def _fake_run_ws(*args):
        return None

    with patch.dict(os.environ, {"MARNEO_FEISHU_ENABLE_CARD_WS_PATCH": "1"}):
        with patch.object(feishu_mod, "_patch_lark_oapi_card_handling") as mock_patch:
            with patch.object(feishu_mod, "_run_feishu_ws_client", side_effect=_fake_run_ws):
                await adapter._start_websocket()
                await adapter._ws_future

    mock_patch.assert_called_once_with()


@pytest.mark.asyncio
async def test_kill_ws_does_not_close_ws_connection_on_gateway_loop():
    """Killing WS must not await the SDK websocket connection on the gateway loop."""
    adapter = FeishuChannelAdapter(MagicMock(), employee_name="test")
    conn = SimpleNamespace(close=MagicMock())
    adapter._ws_client = SimpleNamespace(_conn=conn, _auto_reconnect=True)
    adapter._ws_loop = None

    await adapter._kill_ws()

    assert conn.close.call_count == 0
    assert adapter._ws_client is None
    assert adapter._ws_loop is None


@pytest.mark.asyncio
async def test_card_action_form_submit_resolves_pending_question_as_synthetic_message():
    """Feishu form-submit cards should use the new pending-question registry."""
    from marneo.gateway.pending_questions import (
        PendingQuestionContext,
        _by_chat_context,
        _lock,
        _pending_questions,
        store_pending_question,
    )

    with _lock:
        _pending_questions.clear()
        _by_chat_context.clear()

    manager = SimpleNamespace(dispatch=AsyncMock())
    adapter = FeishuChannelAdapter(manager, employee_name="test")
    adapter._app_id = "app1"
    adapter._loop = asyncio.get_running_loop()

    store_pending_question(PendingQuestionContext(
        question_id="q1",
        chat_id="chat1",
        account_id="app1",
        sender_open_id="ou_user",
        card_id="",
        questions=[{"question": "确认执行？", "header": "确认", "options": [], "multiSelect": False}],
        message_id="m1",
        adapter=adapter,
    ))

    event = SimpleNamespace(
        action=SimpleNamespace(
            name="ask_user_submit_q1",
            value={},
            form_value={"answer_0": "可以执行"},
        ),
        operator=SimpleNamespace(open_id="ou_user"),
        context=SimpleNamespace(open_chat_id="chat1", open_message_id="card_msg1"),
    )
    data = SimpleNamespace(event=event)

    response = adapter._on_card_action(data)
    await asyncio.sleep(0.05)

    assert response is not None
    manager.dispatch.assert_awaited_once()
    sent = manager.dispatch.await_args.args[0]
    assert sent.platform == "feishu:test"
    assert sent.chat_id == "chat1"
    assert sent.user_id == "ou_user"
    assert "确认执行？" in sent.text
    assert "可以执行" in sent.text


@pytest.mark.asyncio
async def test_card_action_form_submit_without_pending_context_does_not_dispatch():
    """Expired/already-consumed ask_user submits should toast, not dispatch bogus empty-chat messages."""
    manager = SimpleNamespace(dispatch=AsyncMock())
    adapter = FeishuChannelAdapter(manager, employee_name="test")
    adapter._app_id = "app1"
    adapter._loop = asyncio.get_running_loop()

    data = SimpleNamespace(event=SimpleNamespace(
        action=SimpleNamespace(
            name="ask_user_submit_missing",
            value={},
            form_value={"answer_0": "late answer"},
        ),
        operator=SimpleNamespace(open_id="ou_user"),
        context=SimpleNamespace(open_chat_id="chat1", open_message_id="card_msg1"),
    ))

    response = adapter._on_card_action(data)
    await asyncio.sleep(0.05)

    assert response is not None
    assert getattr(response, "toast", None)["type"] == "warning"
    manager.dispatch.assert_not_awaited()
