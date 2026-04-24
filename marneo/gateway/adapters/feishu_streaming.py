# marneo/gateway/adapters/feishu_streaming.py
"""Feishu Card Kit streaming card — Python port of openclaw/streaming-card.ts.

Provides real-time typewriter effect for LLM responses in Feishu.

Flow:
  1. start(chat_id)         → POST /cardkit/v1/cards     → create card entity
                            → POST /im/message.create    → send interactive msg
  2. update(text)           → PUT  /cardkit/v1/cards/{id}/elements/content/content
                            → throttled to max 10 updates/sec
  3. close(final_text)      → final PUT + PATCH settings streaming_mode=false
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_UPDATE_INTERVAL = 0.1        # 100ms throttle — max 10 updates/sec
_SUMMARY_MAX = 50             # max chars for card collapse summary
_THINKING_PLACEHOLDER = "⏳ 思考中..."


def merge_streaming_text(previous: str, next_text: str) -> str:
    """Merge streaming text chunks, handling partial overlaps.

    Ported from openclaw mergeStreamingText(). Handles:
    - Empty inputs
    - Superset/subset cases
    - Partial overlaps (e.g. "这是" + "是一" → "这是一")
    - Fallback: append to avoid losing tokens
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

    # Merge partial overlaps
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
        ok = await card.start(chat_id, reply_to_msg_id=msg_id)
        if ok:
            await card.update("partial text...")
            await card.update("growing text...")
            await card.close("final complete text")
    """

    def __init__(self, app_id: str, app_secret: str, domain: str = "feishu") -> None:
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
                chat_id, card_id, reply_to_msg_id=reply_to_msg_id
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
        elements: list[dict] = [
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

        payload = json.dumps(
            {"type": "card_json", "data": json.dumps(card_json, ensure_ascii=False)},
            ensure_ascii=False,
        )
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self._base_url}/cardkit/v1/cards",
                headers=self._auth_headers(token),
                content=payload.encode(),
            )
            data = resp.json()
            if data.get("code") != 0:
                log.warning("[Streaming] Create card failed: %s", data.get("msg"))
                return None
            return data.get("data", {}).get("card_id")

    async def _send_card_message(
        self,
        chat_id: str,
        card_id: str,
        reply_to_msg_id: Optional[str] = None,
    ) -> Optional[str]:
        """Send interactive message referencing card_id. Returns message_id.

        Note: lark SDK authenticates internally via app_id/app_secret.
        """
        card_content = json.dumps(
            {"type": "card", "data": {"card_id": card_id}}, ensure_ascii=False
        )
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest, CreateMessageRequestBody,
                ReplyMessageRequest, ReplyMessageRequestBody,
            )
            lark_domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN
            lark_client = (
                lark.Client.builder()
                .app_id(self._app_id)
                .app_secret(self._app_secret)
                .domain(lark_domain)
                .build()
            )
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
        """PUT content to card element. Updates _current_text only on success."""
        if not self._card_id:
            return
        seq = self._sequence + 1
        try:
            token = await self._fetch_token()
            payload = json.dumps({
                "content": text,
                "sequence": seq,
                "uuid": f"s_{self._card_id}_{seq}",
            }, ensure_ascii=False)
            async with httpx.AsyncClient(timeout=10) as client:
                await client.put(
                    f"{self._base_url}/cardkit/v1/cards/{self._card_id}/elements/content/content",
                    headers=self._auth_headers(token),
                    content=payload.encode(),
                )
            # Only advance state after confirmed delivery
            self._sequence = seq
            self._current_text = text
        except Exception as exc:
            log.debug("[Streaming] _put_content error (state not advanced): %s", exc)

    async def update(self, text: str) -> None:
        """Update card content with throttle (max 10 updates/sec)."""
        if not self._card_id or self._closed:
            return
        merged = merge_streaming_text(self._current_text, text)
        if not merged or merged == self._current_text:
            return

        now = time.monotonic()
        if now - self._last_update_time < _UPDATE_INTERVAL:
            # Throttled — store pending, skip this update
            self._pending_text = merged
            return

        self._pending_text = None
        self._last_update_time = now
        await self._put_content(merged)

    async def close(self, final_text: str = "") -> None:
        """Flush pending, do final content update, disable streaming_mode.

        final_text: the complete authoritative LLM response. If provided,
        it takes precedence over accumulated streaming state. If empty,
        we use current + pending as the final text.
        """
        if self._closed:
            return
        self._closed = True

        if not self._card_id:
            return

        # Determine final text:
        # - If caller provides final_text (complete response), use it directly.
        # - Otherwise merge current + any pending delta.
        if final_text:
            text = final_text
        else:
            pending = self._pending_text or ""
            text = merge_streaming_text(self._current_text, pending)

        # Final content update if different from what's displayed
        if text and text != self._current_text:
            await self._put_content(text)

        # Disable streaming mode + set summary
        try:
            token = await self._fetch_token()
            self._sequence += 1
            summary = _truncate_summary(text or "")
            settings_payload = json.dumps({
                "settings": json.dumps({
                    "config": {
                        "streaming_mode": False,
                        "summary": {"content": summary},
                    }
                }, ensure_ascii=False),
                "sequence": self._sequence,
                "uuid": f"c_{self._card_id}_{self._sequence}",
            }, ensure_ascii=False)
            async with httpx.AsyncClient(timeout=10) as client:
                await client.patch(
                    f"{self._base_url}/cardkit/v1/cards/{self._card_id}/settings",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    content=settings_payload.encode(),
                )
            log.info("[Streaming] Closed: card=%s", self._card_id)
        except Exception as exc:
            log.warning("[Streaming] close() PATCH error: %s", exc)
