import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from marneo.gateway.adapters.feishu import FeishuChannelAdapter


def _message_event(*, msg_id: str, chat_id: str = "chat1", user_id: str = "ou_user", text: str = ""):
    return SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_id=msg_id,
                chat_id=chat_id,
                chat_type="p2p",
                message_type="text",
                content=json.dumps({"text": text}, ensure_ascii=False),
                mentions=[],
            ),
            sender=SimpleNamespace(
                sender_type="user",
                sender_id=SimpleNamespace(open_id=user_id, user_id=""),
            ),
        )
    )


@pytest.mark.asyncio
async def test_rapid_text_messages_from_same_chat_are_dispatched_once_as_batch():
    manager = SimpleNamespace(dispatch=AsyncMock())
    adapter = FeishuChannelAdapter(manager, employee_name="test")
    adapter._text_batch_delay_seconds = 0.01
    adapter._resolve_sender_name = AsyncMock(return_value="Alice")
    adapter._add_reaction = AsyncMock(return_value="")
    adapter._finish_reaction = AsyncMock()

    await adapter._handle_message_event_data(_message_event(msg_id="m1", text="第一段"))
    await adapter._handle_message_event_data(_message_event(msg_id="m2", text="第二段"))
    await asyncio.sleep(0.05)

    manager.dispatch.assert_awaited_once()
    sent = manager.dispatch.await_args.args[0]
    assert sent.platform == "feishu:test"
    assert sent.chat_id == "chat1"
    assert sent.user_id == "ou_user"
    assert sent.msg_id == "m2"
    assert "第一段\n第二段" in sent.text
    assert "[msg:m2]" in sent.text


@pytest.mark.asyncio
async def test_text_batching_keeps_different_users_separate():
    manager = SimpleNamespace(dispatch=AsyncMock())
    adapter = FeishuChannelAdapter(manager, employee_name="test")
    adapter._text_batch_delay_seconds = 0.01
    adapter._resolve_sender_name = AsyncMock(return_value="")
    adapter._add_reaction = AsyncMock(return_value="")
    adapter._finish_reaction = AsyncMock()

    await adapter._handle_message_event_data(_message_event(msg_id="m1", user_id="ou_1", text="用户1"))
    await adapter._handle_message_event_data(_message_event(msg_id="m2", user_id="ou_2", text="用户2"))
    await asyncio.sleep(0.05)

    assert manager.dispatch.await_count == 2
    texts = [call.args[0].text for call in manager.dispatch.await_args_list]
    assert any("用户1" in text for text in texts)
    assert any("用户2" in text for text in texts)


@pytest.mark.asyncio
async def test_text_batching_flushes_existing_batch_when_max_messages_exceeded():
    manager = SimpleNamespace(dispatch=AsyncMock())
    adapter = FeishuChannelAdapter(manager, employee_name="test")
    adapter._text_batch_delay_seconds = 10
    adapter._text_batch_max_messages = 2
    adapter._resolve_sender_name = AsyncMock(return_value="")
    adapter._add_reaction = AsyncMock(return_value="")
    adapter._finish_reaction = AsyncMock()

    await adapter._handle_message_event_data(_message_event(msg_id="m1", text="one"))
    await adapter._handle_message_event_data(_message_event(msg_id="m2", text="two"))
    await adapter._handle_message_event_data(_message_event(msg_id="m3", text="three"))

    assert manager.dispatch.await_count == 1
    first = manager.dispatch.await_args.args[0]
    assert first.msg_id == "m2"
    assert "one\ntwo" in first.text

    await adapter._flush_text_batch_now(adapter._text_batch_key(first))
    assert manager.dispatch.await_count == 2
    second = manager.dispatch.await_args.args[0]
    assert second.msg_id == "m3"
    assert "three" in second.text
