# tests/gateway/test_streaming_integration.py
"""Integration tests for streaming card wiring in GatewayManager."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from marneo.gateway.base import ChannelMessage, BaseChannelAdapter
from marneo.gateway.adapters.feishu import FeishuChannelAdapter
from marneo.engine.chat import ChatEvent


class FakeTextAdapter(BaseChannelAdapter):
    """Non-Feishu adapter for testing fallback path."""
    def __init__(self):
        super().__init__("fake")
        self.replies = []
        self._running = True
    async def connect(self, config): return True
    async def disconnect(self): pass
    async def send_reply(self, chat_id, text, **kw):
        self.replies.append(text)
        return True


@pytest.mark.asyncio
async def test_feishu_adapter_has_process_streaming():
    manager = MagicMock()
    adapter = FeishuChannelAdapter(manager, employee_name="test")
    assert hasattr(adapter, "process_streaming")
    assert callable(adapter.process_streaming)


@pytest.mark.asyncio
async def test_gateway_uses_text_fallback_for_non_feishu():
    """Non-Feishu adapters (no process_streaming) use text send_reply."""
    from marneo.gateway.manager import GatewayManager
    from marneo.gateway.session import SessionStore

    manager = GatewayManager()
    adapter = FakeTextAdapter()
    manager.register(adapter)

    msg = ChannelMessage(platform="fake", chat_id="c1", text="hello")

    async def fake_send(text, registry=None, max_iterations=20, attachments=None):
        yield ChatEvent(type="text", content="response text")
        yield ChatEvent(type="done")

    store = SessionStore()
    engine, lock = await store.get_or_create("fake", "c1")
    with patch.object(engine, "send_with_tools", side_effect=fake_send):
        async with lock:
            await manager._process(msg, engine, adapter)

    assert adapter.replies == ["response text"]


@pytest.mark.asyncio
async def test_process_streaming_falls_back_when_card_fails():
    """process_streaming falls back to send_reply when card creation fails."""
    manager = MagicMock()
    adapter = FeishuChannelAdapter(manager, employee_name="test")
    adapter._app_id = "aid"
    adapter._app_secret = "asec"
    adapter._domain = "feishu"
    adapter._running = True

    replies = []
    async def fake_send_reply(chat_id, text, **kw):
        replies.append(text)
        return True
    adapter.send_reply = fake_send_reply

    async def fake_engine_send(text, registry=None, max_iterations=20, attachments=None):
        yield ChatEvent(type="text", content="fallback text")
        yield ChatEvent(type="done")

    engine = MagicMock()
    engine.send_with_tools = fake_engine_send

    # Patch FeishuStreamingCard.start to return False (card creation fails)
    with patch("marneo.gateway.adapters.feishu.FeishuStreamingCard") as MockCard:
        mock_card = AsyncMock()
        mock_card.start = AsyncMock(return_value=False)
        MockCard.return_value = mock_card

        msg = ChannelMessage(platform="feishu:test", chat_id="c1", text="hello", msg_id="m1")
        from marneo.tools.registry import ToolRegistry
        await adapter.process_streaming(msg, engine, ToolRegistry())

    assert replies == ["fallback text"]


@pytest.mark.asyncio
async def test_channel_message_has_user_name():
    msg = ChannelMessage(platform="p", chat_id="c", text="t", user_name="张三")
    assert msg.user_name == "张三"
