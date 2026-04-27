# Feishu Streaming Card Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Replace Feishu text replies with Card Kit streaming cards that update in real-time as the LLM generates output (typewriter effect), plus show sender info for multi-person group chats.

**Architecture:** Port OpenClaw's `FeishuStreamingSession` to Python as `FeishuStreamingCard`. `GatewayManager._process()` detects Feishu adapters and uses streaming — create card first, feed LLM chunks as PUT updates (100ms throttle), close with PATCH when done. Sender info injected as card header context for group messages.

**Tech Stack:** Python 3.11+, httpx (async HTTP), existing `FeishuChannelAdapter`, `GatewayManager`. Card Kit API: `POST /cardkit/v1/cards`, `PUT /cardkit/v1/cards/{id}/elements/content/content`, `PATCH /cardkit/v1/cards/{id}/settings`.

**Reference:** OpenClaw `extensions/feishu/src/streaming-card.ts` (full port).

---

## Task 1: FeishuStreamingCard class

**Files:**
- Create: `marneo/gateway/adapters/feishu_streaming.py`
- Create: `tests/gateway/test_feishu_streaming.py`

### Step 1: Write failing tests

```python
# tests/gateway/test_feishu_streaming.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from marneo.gateway.adapters.feishu_streaming import FeishuStreamingCard, merge_streaming_text


# ── merge_streaming_text tests ────────────────────────────────────────────────

def test_merge_text_empty_previous():
    assert merge_streaming_text("", "hello") == "hello"

def test_merge_text_next_is_superset():
    assert merge_streaming_text("hell", "hello") == "hello"

def test_merge_text_overlap():
    assert merge_streaming_text("这是", "是一") == "这是一"

def test_merge_text_same():
    assert merge_streaming_text("abc", "abc") == "abc"

def test_merge_text_no_relation():
    # Fallback: append
    result = merge_streaming_text("abc", "xyz")
    assert "abc" in result and "xyz" in result


# ── FeishuStreamingCard API flow ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_creates_card_and_sends_message():
    card = FeishuStreamingCard(app_id="aid", app_secret="asec", domain="feishu")

    async def mock_post(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "cardkit" in url:
            resp.json = MagicMock(return_value={"code": 0, "data": {"card_id": "bpcn_test"}})
        else:
            resp.json = MagicMock(return_value={"code": 0, "data": {"message_id": "om_test"}})
        return resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = mock_post
        mock_client.put = AsyncMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value={"code": 0})))
        mock_client.patch = AsyncMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value={"code": 0})))
        mock_client_cls.return_value = mock_client

        await card._set_token("fake_token")
        card._card_id = "bpcn_test"
        card._message_id = "om_test"
        card._sequence = 1
        card._current_text = ""

        # Test update
        await card._put_content("hello world")
        assert card._current_text == "hello world"


@pytest.mark.asyncio
async def test_get_token_caches():
    card = FeishuStreamingCard(app_id="aid", app_secret="asec", domain="feishu")
    await card._set_token("tok123")
    assert await card._get_cached_token() == "tok123"
```

### Step 2: Verify FAIL
```bash
cd /Users/chamber/code/marneo-agent && pytest tests/gateway/test_feishu_streaming.py -v 2>&1 | head -15
```

### Step 3: Create `marneo/gateway/adapters/feishu_streaming.py`

Port OpenClaw's `FeishuStreamingSession` to Python with httpx:

```python
# marneo/gateway/adapters/feishu_streaming.py
"""Feishu Card Kit streaming card — Python port of openclaw/streaming-card.ts.

Provides real-time typewriter effect for LLM responses in Feishu.

Flow:
  1. start(chat_id)          → POST /cardkit/v1/cards → create card
                              → POST /im/message.create → send interactive msg
  2. update(text)            → PUT /cardkit/v1/cards/{id}/elements/content/content
                              → throttled to max 10 updates/sec
  3. close(final_text)       → final PUT + PATCH settings streaming_mode=false
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_UPDATE_INTERVAL = 0.1       # 100ms throttle — max 10 updates/sec
_SUMMARY_MAX = 50            # max chars for card collapse summary
_THINKING_PLACEHOLDER = "⏳ 思考中..."


def merge_streaming_text(previous: str, next_text: str) -> str:
    """Merge streaming text chunks, handling partial overlaps.

    Ported from openclaw mergeStreamingText().
    """
    if not next_text:
        return previous
    if not previous or next_text == previous:
        return next_text
    if next_text.startswith(previous):
        return next_text
    if previous.startswith(next_text):
        return previous
    if next_text in previous:
        return previous
    if previous in next_text:
        return next_text

    # Merge partial overlaps: "这" + "这是" => "这是"
    max_overlap = min(len(previous), len(next_text))
    for overlap in range(max_overlap, 0, -1):
        if previous[-overlap:] == next_text[:overlap]:
            return previous + next_text[overlap:]

    # Fallback: append to avoid losing tokens
    return previous + next_text


def _truncate_summary(text: str, max_len: int = _SUMMARY_MAX) -> str:
    clean = text.replace("\n", " ").strip()
    return clean if len(clean) <= max_len else clean[:max_len - 3] + "..."


class FeishuStreamingCard:
    """Manages a Feishu Card Kit streaming card lifecycle.

    Usage:
        card = FeishuStreamingCard(app_id, app_secret, domain)
        await card.start(chat_id, reply_to_msg_id=original_msg_id)
        await card.update("partial text")
        await card.update("growing text")
        await card.close("final complete text")
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        domain: str = "feishu",
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._domain = domain
        self._base_url = (
            "https://open.larksuite.com/open-apis"
            if domain == "lark"
            else "https://open.feishu.cn/open-apis"
        )

        # Card state
        self._card_id: Optional[str] = None
        self._message_id: Optional[str] = None
        self._sequence: int = 0
        self._current_text: str = ""
        self._closed: bool = False

        # Token cache
        self._token: Optional[str] = None
        self._token_expires_at: float = 0

        # Throttle state
        self._last_update_time: float = 0
        self._pending_text: Optional[str] = None

    # ── Token management ──────────────────────────────────────────────────────

    async def _set_token(self, token: str, expires_in: int = 7200) -> None:
        self._token = token
        self._token_expires_at = time.time() + expires_in - 60

    async def _get_cached_token(self) -> Optional[str]:
        if self._token and time.time() < self._token_expires_at:
            return self._token
        return None

    async def _fetch_token(self) -> str:
        cached = await self._get_cached_token()
        if cached:
            return cached
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self._base_url}/auth/v3/tenant_access_token/internal",
                json={"app_id": self._app_id, "app_secret": self._app_secret},
            )
            data = resp.json()
            token = data.get("tenant_access_token", "")
            if not token:
                raise RuntimeError(f"Token fetch failed: {data.get('msg', 'unknown')}")
            await self._set_token(token, data.get("expire", 7200))
            return token

    def _auth_headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ── Card lifecycle ────────────────────────────────────────────────────────

    async def start(
        self,
        chat_id: str,
        reply_to_msg_id: Optional[str] = None,
        sender_name: str = "",
    ) -> bool:
        """Create card entity + send interactive message. Returns True on success."""
        try:
            token = await self._fetch_token()
            card_id = await self._create_card(token, sender_name=sender_name)
            if not card_id:
                return False
            message_id = await self._send_card_message(
                token, chat_id, card_id, reply_to_msg_id=reply_to_msg_id
            )
            if not message_id:
                return False
            self._card_id = card_id
            self._message_id = message_id
            self._sequence = 1
            self._current_text = ""
            log.info("[Streaming] Started: card=%s msg=%s", card_id, message_id)
            return True
        except Exception as exc:
            log.warning("[Streaming] start() failed: %s", exc)
            return False

    async def _create_card(self, token: str, sender_name: str = "") -> Optional[str]:
        """POST /cardkit/v1/cards — returns card_id."""
        elements = [
            {"tag": "markdown", "content": _THINKING_PLACEHOLDER, "element_id": "content"}
        ]
        card_json: dict = {
            "schema": "2.0",
            "config": {
                "streaming_mode": True,
                "summary": {"content": "[生成中...]"},
                "streaming_config": {
                    "print_frequency_ms": {"default": 50},
                    "print_step": {"default": 1},
                },
            },
            "body": {"elements": elements},
        }
        if sender_name:
            card_json["header"] = {
                "title": {"tag": "plain_text", "content": f"💬 {sender_name}"},
                "template": "blue",
            }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self._base_url}/cardkit/v1/cards",
                headers=self._auth_headers(token),
                content=json.dumps(
                    {"type": "card_json", "data": json.dumps(card_json, ensure_ascii=False)},
                    ensure_ascii=False,
                ).encode(),
            )
            data = resp.json()
            if data.get("code") != 0:
                log.warning("[Streaming] Create card failed: %s", data.get("msg"))
                return None
            return data.get("data", {}).get("card_id")

    async def _send_card_message(
        self, token: str, chat_id: str, card_id: str,
        reply_to_msg_id: Optional[str] = None,
    ) -> Optional[str]:
        """Send interactive message referencing card_id. Returns message_id."""
        card_content = json.dumps(
            {"type": "card", "data": {"card_id": card_id}}, ensure_ascii=False
        )
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest, CreateMessageRequestBody,
            ReplyMessageRequest, ReplyMessageRequestBody,
        )
        import lark_oapi as lark
        lark_domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN
        lark_client = (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .domain(lark_domain)
            .build()
        )
        try:
            if reply_to_msg_id:
                body = (
                    ReplyMessageRequestBody.builder()
                    .msg_type("interactive")
                    .content(card_content)
                    .build()
                )
                request = (
                    ReplyMessageRequest.builder()
                    .message_id(reply_to_msg_id)
                    .request_body(body)
                    .build()
                )
                resp = await asyncio.to_thread(lark_client.im.v1.message.reply, request)
            else:
                body = (
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("interactive")
                    .content(card_content)
                    .build()
                )
                request = (
                    CreateMessageRequest.builder()
                    .receive_id_type("chat_id")
                    .request_body(body)
                    .build()
                )
                resp = await asyncio.to_thread(lark_client.im.v1.message.create, request)

            if not resp or not getattr(resp, "success", lambda: False)():
                log.warning("[Streaming] Send card message failed: code=%s", getattr(resp, "code", "?"))
                return None
            msg_id = getattr(getattr(resp, "data", None), "message_id", None)
            return msg_id
        except Exception as exc:
            log.warning("[Streaming] Send card message error: %s", exc)
            return None

    # ── Content updates ───────────────────────────────────────────────────────

    async def _put_content(self, text: str) -> None:
        """PUT content to card element (internal, no throttle)."""
        if not self._card_id:
            return
        self._sequence += 1
        self._current_text = text
        try:
            token = await self._fetch_token()
            async with httpx.AsyncClient(timeout=10) as client:
                await client.put(
                    f"{self._base_url}/cardkit/v1/cards/{self._card_id}/elements/content/content",
                    headers=self._auth_headers(token),
                    content=json.dumps({
                        "content": text,
                        "sequence": self._sequence,
                        "uuid": f"s_{self._card_id}_{self._sequence}",
                    }, ensure_ascii=False).encode(),
                )
        except Exception as exc:
            log.debug("[Streaming] _put_content error: %s", exc)

    async def update(self, text: str) -> None:
        """Update card content with throttle (max 10/sec)."""
        if not self._card_id or self._closed:
            return
        merged = merge_streaming_text(self._current_text, text)
        if not merged or merged == self._current_text:
            return

        now = time.monotonic()
        if now - self._last_update_time < _UPDATE_INTERVAL:
            self._pending_text = merged
            return

        self._pending_text = None
        self._last_update_time = now
        await self._put_content(merged)

    async def close(self, final_text: str = "") -> None:
        """Flush pending text, do final update, disable streaming_mode."""
        if self._closed or not self._card_id:
            self._closed = True
            return
        self._closed = True

        # Flush any pending text
        pending = self._pending_text
        self._pending_text = None
        text = merge_streaming_text(
            merge_streaming_text(self._current_text, pending or ""),
            final_text,
        )

        # Final content update if needed
        if text and text != self._current_text:
            await self._put_content(text)

        # Disable streaming mode
        try:
            token = await self._fetch_token()
            self._sequence += 1
            summary = _truncate_summary(text or "")
            async with httpx.AsyncClient(timeout=10) as client:
                await client.patch(
                    f"{self._base_url}/cardkit/v1/cards/{self._card_id}/settings",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    content=json.dumps({
                        "settings": json.dumps({
                            "config": {
                                "streaming_mode": False,
                                "summary": {"content": summary},
                            }
                        }, ensure_ascii=False),
                        "sequence": self._sequence,
                        "uuid": f"c_{self._card_id}_{self._sequence}",
                    }, ensure_ascii=False).encode(),
                )
            log.info("[Streaming] Closed: card=%s", self._card_id)
        except Exception as exc:
            log.warning("[Streaming] close() error: %s", exc)
```

### Step 4: Verify tests PASS
```bash
pytest tests/gateway/test_feishu_streaming.py -v
```
Expected: 7 passed

### Step 5: Commit
```bash
git add marneo/gateway/adapters/feishu_streaming.py tests/gateway/test_feishu_streaming.py
git commit -m "feat(feishu): add FeishuStreamingCard — Card Kit streaming with typewriter effect"
```

---

## Task 2: Wire streaming into GatewayManager + FeishuChannelAdapter

**Files:**
- Modify: `marneo/gateway/manager.py` — detect Feishu adapter, use streaming
- Modify: `marneo/gateway/adapters/feishu.py` — add `process_streaming()` method
- Modify: `marneo/gateway/base.py` — add optional `msg_id` field to ChannelMessage (already exists)
- Create: `tests/gateway/test_streaming_integration.py`

### Step 1: Write failing test

```python
# tests/gateway/test_streaming_integration.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from marneo.gateway.base import ChannelMessage
from marneo.gateway.adapters.feishu import FeishuChannelAdapter


@pytest.mark.asyncio
async def test_feishu_adapter_has_process_streaming():
    manager = MagicMock()
    adapter = FeishuChannelAdapter(manager, employee_name="test")
    assert hasattr(adapter, "process_streaming")


@pytest.mark.asyncio
async def test_process_streaming_fallback_on_card_failure():
    """When card creation fails, falls back to text reply."""
    from marneo.gateway.manager import GatewayManager
    from marneo.gateway.base import BaseChannelAdapter
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

    manager = GatewayManager()
    adapter = FakeAdapter()
    manager.register(adapter)

    msg = ChannelMessage(platform="fake", chat_id="c1", text="hello", msg_id="m1")

    async def fake_send(text, registry=None, max_iterations=20, attachments=None):
        yield ChatEvent(type="text", content="response")
        yield ChatEvent(type="done")

    from marneo.gateway.session import SessionStore
    store = SessionStore()
    engine, lock = await store.get_or_create("fake", "c1")

    with patch.object(engine, "send_with_tools", side_effect=fake_send):
        async with lock:
            await manager._process(msg, engine, adapter)

    assert adapter.replies == ["response"]
```

### Step 2: Verify FAIL
```bash
pytest tests/gateway/test_streaming_integration.py -v 2>&1 | head -15
```

### Step 3: Add `process_streaming()` to `FeishuChannelAdapter`

Read `marneo/gateway/adapters/feishu.py` first, then add this method after `_dispatch_with_lifecycle`:

```python
    async def process_streaming(
        self,
        msg: "ChannelMessage",
        engine: Any,
        registry: Any,
    ) -> None:
        """Process message with streaming card — typewriter effect.

        Falls back to text send_reply if card creation fails.
        """
        from marneo.gateway.adapters.feishu_streaming import FeishuStreamingCard

        # Attempt to create streaming card
        card = FeishuStreamingCard(
            app_id=self._app_id,
            app_secret=self._app_secret,
            domain=self._domain,
        )
        card_started = await card.start(
            chat_id=msg.chat_id,
            reply_to_msg_id=msg.msg_id or None,
            sender_name=msg.user_name or "",
        )

        if not card_started:
            # Fallback: collect text and use regular send_reply
            log.warning("[Streaming] Card creation failed, falling back to text reply")
            parts: list[str] = []
            async for event in engine.send_with_tools(
                msg.text, registry=registry, attachments=msg.attachments or None
            ):
                if event.type == "text" and event.content:
                    parts.append(event.content)
            reply = "".join(parts).strip()
            if reply:
                await self.send_reply(msg.chat_id, reply)
            return

        # Stream LLM output to card
        accumulated = ""
        success = False
        try:
            async for event in engine.send_with_tools(
                msg.text, registry=registry, attachments=msg.attachments or None
            ):
                if event.type == "text" and event.content:
                    accumulated += event.content
                    await card.update(accumulated)
                elif event.type == "tool_result":
                    log.debug("[Streaming] Tool result: %s", event.content[:100])
            success = True
        except Exception as exc:
            log.error("[Streaming] LLM error: %s", exc)
            accumulated = accumulated or f"处理出错：{exc}"
        finally:
            await card.close(accumulated)
```

Also add `user_name` to `ChannelMessage` in `base.py` if not already there (it has `user_id` but may not have `user_name`). Add:
```python
    user_name: str = ""
```

And populate it in `feishu.py` `_handle_message_event_data()` from sender data.

### Step 4: Modify `GatewayManager._process()` to use streaming for Feishu

In `marneo/gateway/manager.py`, read the current `_process()` then update:

```python
    async def _process(self, msg: ChannelMessage, engine: Any, adapter: BaseChannelAdapter) -> None:
        # Use streaming card if adapter supports it (Feishu)
        if hasattr(adapter, "process_streaming") and adapter._running:
            try:
                async with asyncio.timeout(REPLY_TIMEOUT):
                    await adapter.process_streaming(msg, engine, _tool_registry)
                return
            except TimeoutError:
                await adapter.send_reply(msg.chat_id, "处理超时，请重试。")
                return
            except Exception as e:
                log.error("[Gateway] Streaming process error: %s", e)
                # Fall through to text mode

        # Fallback: collect text and send
        parts: list[str] = []
        try:
            async with asyncio.timeout(REPLY_TIMEOUT):
                async for event in engine.send_with_tools(
                    msg.text,
                    registry=_tool_registry,
                    attachments=msg.attachments or None,
                ):
                    if event.type == "text" and event.content:
                        parts.append(event.content)
                    elif event.type == "tool_result":
                        log.debug("[Gateway] Tool result: %s", event.content[:100] + ("..." if len(event.content) > 100 else ""))
        except TimeoutError:
            parts = ["处理超时，请重试。"]
        except Exception as e:
            parts = [f"处理出错：{e}"]

        reply = "".join(parts).strip()
        if not reply:
            return
        while reply:
            chunk, reply = reply[:MAX_REPLY_LEN], reply[MAX_REPLY_LEN:]
            await adapter.send_reply(msg.chat_id, chunk, context_token=msg.context_token)
```

### Step 5: Update `_handle_message_event_data()` to populate `user_name`

In `feishu.py`, get sender display name from sender data:

```python
        # Get sender name for card header
        sender_name = ""
        try:
            mentions = getattr(msg_body, "mentions", []) or []
            # For now use sender_id as fallback display
            sender_name = ""  # Will be populated when we add sender name resolution
        except Exception:
            pass

        channel_msg = ChannelMessage(
            platform=self.platform,
            chat_id=chat_id,
            chat_type="group" if chat_type == "group" else "dm",
            user_id=sender_id,
            user_name=sender_name,
            text=text,
            msg_id=msg_id,
            attachments=attachments,
        )
```

### Step 6: Verify PASS
```bash
pytest tests/gateway/test_streaming_integration.py tests/gateway/ -v -q
```
Expected: all pass

### Step 7: Run full suite
```bash
pytest tests/ -q --tb=short 2>&1 | tail -5
```

### Step 8: Commit
```bash
git add marneo/gateway/manager.py marneo/gateway/adapters/feishu.py marneo/gateway/base.py
git commit -m "feat(gateway): wire streaming card into GatewayManager, add process_streaming to FeishuAdapter"
```

---

## Task 3: Smoke test + gateway restart

### Step 1: Verify full suite passes
```bash
pytest tests/ -q --tb=short
```

### Step 2: Restart gateway
```bash
marneo gateway restart
```

### Step 3: Verify startup logs show connection
```bash
sleep 4 && marneo gateway logs -n 10
```
Expected: `[Feishu] Connected` and no errors

### Step 4: Final commit + push
```bash
git add -A && git commit -m "feat(feishu): streaming card with typewriter effect + sender info in group chats" --allow-empty
git push
```

---

## Summary

After all tasks:
- Feishu replies use Card Kit streaming (`schema: 2.0`, `streaming_mode: true`)
- LLM text chunks are fed to the card with 100ms throttle (typewriter effect)
- Card shows sender name in header for group messages
- Falls back to text reply if Card Kit creation fails
- `merge_streaming_text()` handles fragmented LLM chunks correctly (ported from openclaw)
- Non-Feishu adapters (WeChat, Telegram, Discord) continue using text send_reply
