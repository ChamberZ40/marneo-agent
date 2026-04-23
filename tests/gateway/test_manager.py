"""Tests for gateway manager dedup and routing."""
from marneo.gateway.manager import GatewayManager, _Dedup
from marneo.gateway.base import ChannelMessage, BaseChannelAdapter
from typing import Any


def test_dedup_new_message():
    d = _Dedup()
    assert not d.seen("msg1")


def test_dedup_repeated_message():
    d = _Dedup()
    d.seen("msg2")
    assert d.seen("msg2")


def test_dedup_different_messages():
    d = _Dedup()
    assert not d.seen("msg3")
    assert not d.seen("msg4")


def test_dedup_empty_id():
    d = _Dedup()
    # Empty msg_id should not be flagged as duplicate
    assert not d.seen("")
    assert not d.seen("")  # second call also False


def test_gateway_register_adapter():
    class FakeAdapter(BaseChannelAdapter):
        def __init__(self): super().__init__("fake")
        async def connect(self, config): return True
        async def disconnect(self): pass
        async def send_reply(self, chat_id, text, **kw): return True

    mgr = GatewayManager()
    mgr.register(FakeAdapter())
    assert "fake" in mgr._adapters


def test_gateway_session_count_starts_zero():
    mgr = GatewayManager()
    assert mgr._sessions.active_count == 0


def test_channel_message_has_attachments_field():
    from marneo.gateway.base import ChannelMessage
    msg = ChannelMessage(platform="test", chat_id="c1", text="hello")
    assert hasattr(msg, "attachments")
    assert msg.attachments == []


def test_channel_message_attachments_with_data():
    from marneo.gateway.base import ChannelMessage
    att = {"data": b"bytes", "media_type": "image/jpeg", "filename": "photo.jpg"}
    msg = ChannelMessage(platform="test", chat_id="c1", text="look", attachments=[att])
    assert len(msg.attachments) == 1
    assert msg.attachments[0]["media_type"] == "image/jpeg"
