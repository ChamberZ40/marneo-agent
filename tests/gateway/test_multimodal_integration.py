# tests/gateway/test_multimodal_integration.py
import pytest
from unittest.mock import patch
from marneo.gateway.manager import GatewayManager
from marneo.gateway.base import ChannelMessage, BaseChannelAdapter
from marneo.engine.chat import ChatEvent


class FakeAdapter(BaseChannelAdapter):
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
async def test_process_passes_attachments_to_send_with_tools():
    """Attachments from ChannelMessage are forwarded to send_with_tools."""
    manager = GatewayManager()
    adapter = FakeAdapter()
    manager.register(adapter)

    att = {"data": b"\xff\xd8\xff", "media_type": "image/jpeg", "filename": "photo.jpg"}
    msg = ChannelMessage(platform="fake", chat_id="c1", text="describe this", attachments=[att])

    received_attachments = []

    async def fake_send_with_tools(text, registry=None, max_iterations=20, attachments=None):
        received_attachments.extend(attachments or [])
        yield ChatEvent(type="text", content="it's a photo")
        yield ChatEvent(type="done")

    from marneo.gateway.session import SessionStore
    store = SessionStore()
    engine, lock = await store.get_or_create("fake", "c1")

    with patch.object(engine, "send_with_tools", side_effect=fake_send_with_tools):
        async with lock:
            await manager._process(msg, engine, adapter)

    assert len(received_attachments) == 1
    assert received_attachments[0]["media_type"] == "image/jpeg"
    assert adapter.replies == ["it's a photo"]


@pytest.mark.asyncio
async def test_process_no_attachments_passes_none():
    """Message with no attachments passes attachments=None to send_with_tools."""
    manager = GatewayManager()
    adapter = FakeAdapter()
    manager.register(adapter)

    msg = ChannelMessage(platform="fake", chat_id="c2", text="hello")
    received_attachments = ["sentinel"]  # will be replaced

    async def fake_send_with_tools(text, registry=None, max_iterations=20, attachments=None):
        received_attachments.clear()
        received_attachments.append(attachments)
        yield ChatEvent(type="text", content="hi")
        yield ChatEvent(type="done")

    from marneo.gateway.session import SessionStore
    store = SessionStore()
    engine, lock = await store.get_or_create("fake", "c2")

    with patch.object(engine, "send_with_tools", side_effect=fake_send_with_tools):
        async with lock:
            await manager._process(msg, engine, adapter)

    # Empty list should be passed as None (falsy check)
    assert received_attachments[0] is None or received_attachments[0] == []
