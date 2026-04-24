# tests/gateway/test_feishu_streaming.py
"""Tests for FeishuStreamingCard and merge_streaming_text."""
import pytest
from marneo.gateway.adapters.feishu_streaming import merge_streaming_text, FeishuStreamingCard


# ── merge_streaming_text ──────────────────────────────────────────────────────

def test_merge_empty_previous():
    assert merge_streaming_text("", "hello") == "hello"


def test_merge_next_is_superset():
    assert merge_streaming_text("hell", "hello") == "hello"


def test_merge_overlap():
    # "这是" + "是一" → "这是一"
    assert merge_streaming_text("这是", "是一") == "这是一"


def test_merge_same():
    assert merge_streaming_text("abc", "abc") == "abc"


def test_merge_no_relation_appends():
    result = merge_streaming_text("abc", "xyz")
    assert "abc" in result and "xyz" in result


def test_merge_next_empty():
    assert merge_streaming_text("hello", "") == "hello"


def test_merge_previous_contained_in_next():
    assert merge_streaming_text("ab", "abcdef") == "abcdef"


# ── FeishuStreamingCard state ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_streaming_card_initial_state():
    card = FeishuStreamingCard(app_id="aid", app_secret="asec", domain="feishu")
    assert card._card_id is None
    assert card._message_id is None
    assert card._current_text == ""
    assert card._closed is False
    assert card._sequence == 0


@pytest.mark.asyncio
async def test_update_before_start_is_noop():
    """update() before start() should not crash."""
    card = FeishuStreamingCard(app_id="aid", app_secret="asec", domain="feishu")
    await card.update("some text")  # must not raise
    assert card._current_text == ""


@pytest.mark.asyncio
async def test_close_before_start_is_noop():
    """close() before start() should not crash."""
    card = FeishuStreamingCard(app_id="aid", app_secret="asec", domain="feishu")
    await card.close("final")  # must not raise
    assert card._closed is True


@pytest.mark.asyncio
async def test_token_caching():
    card = FeishuStreamingCard(app_id="aid", app_secret="asec", domain="feishu")
    await card._set_token("tok123", expires_in=7200)
    cached = await card._get_cached_token()
    assert cached == "tok123"


@pytest.mark.asyncio
async def test_update_throttle():
    """Rapid updates within 100ms should be throttled."""
    import time
    card = FeishuStreamingCard(app_id="aid", app_secret="asec", domain="feishu")
    # Manually set state to simulate started card
    card._card_id = "bpcn_test"
    card._message_id = "om_test"
    card._sequence = 1
    card._current_text = ""
    card._last_update_time = time.monotonic()  # mark as just updated

    put_calls = []
    async def fake_put(text):
        put_calls.append(text)
        card._current_text = text

    card._put_content = fake_put

    await card.update("chunk1")
    # Should be throttled — pending stored, no PUT call
    assert len(put_calls) == 0
    assert card._pending_text == "chunk1"
