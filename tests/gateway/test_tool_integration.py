# tests/gateway/test_tool_integration.py
import pytest
from unittest.mock import patch
from marneo.gateway.manager import GatewayManager
from marneo.gateway.base import ChannelMessage, BaseChannelAdapter
from marneo.engine.chat import ChatSession, ChatEvent


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
async def test_process_uses_send_with_tools():
    """GatewayManager._process uses send_with_tools, not send."""
    manager = GatewayManager()
    adapter = FakeAdapter()
    manager.register(adapter)

    msg = ChannelMessage(platform="fake", chat_id="c1", text="hello")

    async def fake_send_with_tools(text, registry=None, max_iterations=20):
        yield ChatEvent(type="text", content="hi there")
        yield ChatEvent(type="done")

    from marneo.gateway.session import SessionStore
    store = SessionStore()
    engine, lock = await store.get_or_create("fake", "c1")

    with patch.object(engine, "send_with_tools", side_effect=fake_send_with_tools):
        async with lock:
            await manager._process(msg, engine, adapter)

    assert adapter.replies == ["hi there"]


@pytest.mark.asyncio
async def test_process_ignores_tool_result_events():
    """tool_result events are not sent as replies."""
    manager = GatewayManager()
    adapter = FakeAdapter()
    manager.register(adapter)

    msg = ChannelMessage(platform="fake", chat_id="c1", text="run tool")

    import json
    async def fake_with_tool_result(text, registry=None, max_iterations=20):
        yield ChatEvent(type="tool_result", content=json.dumps({"ok": True}))
        yield ChatEvent(type="text", content="Done!")
        yield ChatEvent(type="done")

    from marneo.gateway.session import SessionStore
    store = SessionStore()
    engine, lock = await store.get_or_create("fake", "c1")

    with patch.object(engine, "send_with_tools", side_effect=fake_with_tool_result):
        async with lock:
            await manager._process(msg, engine, adapter)

    assert adapter.replies == ["Done!"]
