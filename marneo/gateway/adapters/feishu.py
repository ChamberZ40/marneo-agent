# marneo/gateway/adapters/feishu.py
"""Feishu / Lark channel adapter.

Uses lark-oapi WebSocket long connection for receiving events.
Uses lark-oapi REST API for sending replies.

Setup requirements:
  - app_id: Feishu app ID (from open.feishu.cn)
  - app_secret: Feishu app secret
  - domain: "feishu" (China) or "lark" (International), default "feishu"
  - dm_policy: "open" | "allowlist" | "disabled", default "open"
  - group_policy: "at_only" | "open" | "disabled", default "at_only"
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, TYPE_CHECKING

from marneo.gateway.base import BaseChannelAdapter, ChannelMessage

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

MAX_MSG_LEN = 4000  # Feishu rich text limit per message


def _check_feishu_available() -> bool:
    try:
        import lark_oapi  # noqa: F401
        return True
    except ImportError:
        return False


class FeishuChannelAdapter(BaseChannelAdapter):
    """Feishu/Lark adapter using lark-oapi WebSocket."""

    def __init__(self, manager: Any) -> None:
        super().__init__("feishu")
        self._manager = manager
        self._app_id = ""
        self._app_secret = ""
        self._domain = "feishu"
        self._dm_policy = "open"
        self._group_policy = "at_only"
        self._bot_open_id = ""
        self._ws_client: Any = None

    def validate_config(self, config: dict[str, str]) -> tuple[bool, str]:
        if not config.get("app_id"):
            return False, "app_id is required"
        if not config.get("app_secret"):
            return False, "app_secret is required"
        return True, ""

    async def connect(self, config: dict[str, str]) -> bool:
        if not _check_feishu_available():
            log.error("[Feishu] lark-oapi is not installed")
            return False

        ok, err = self.validate_config(config)
        if not ok:
            log.error("[Feishu] Config error: %s", err)
            return False

        self._app_id = config["app_id"]
        self._app_secret = config["app_secret"]
        self._domain = config.get("domain", "feishu")
        self._dm_policy = config.get("dm_policy", "open")
        self._group_policy = config.get("group_policy", "at_only")

        try:
            await self._start_websocket()
            self._running = True
            log.info("[Feishu] Connected (domain=%s)", self._domain)
            return True
        except Exception as exc:
            log.error("[Feishu] Connect failed: %s", exc, exc_info=True)
            return False

    async def _start_websocket(self) -> None:
        """Start lark-oapi WebSocket client in background thread."""
        import lark_oapi as lark
        from lark_oapi.ws import Client as FeishuWSClient

        handler = lark.EventDispatcherHandler.builder(
            "", ""
        ).register_p2_im_message_receive_v1(
            self._on_message_receive
        ).build()

        domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN
        # WSClient takes direct args — no .builder() pattern
        self._ws_client = FeishuWSClient(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=handler,
            domain=domain,
        )

        # Run in background thread (lark-oapi WebSocket is synchronous)
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, self._ws_client.start)

    def _on_message_receive(self, data: Any) -> None:
        """Called by lark-oapi when a message arrives."""
        try:
            msg_body = data.event.message
            sender = data.event.sender

            msg_type = msg_body.message_type
            if msg_type != "text":
                return  # v1: text only

            content = json.loads(msg_body.content or "{}")
            text = content.get("text", "").strip()
            if not text:
                return

            chat_id = msg_body.chat_id or ""
            chat_type = msg_body.chat_type or "p2p"  # "p2p" or "group"
            user_id = sender.sender_id.open_id if sender.sender_id else ""
            msg_id = msg_body.message_id or ""

            # Group policy: only respond to @mentions
            if chat_type == "group":
                if self._group_policy == "disabled":
                    return
                if self._group_policy == "at_only":
                    # Check if bot was mentioned
                    mentions = msg_body.mentions or []
                    bot_mentioned = any(
                        m.id.open_id == self._bot_open_id for m in mentions
                    ) if self._bot_open_id else bool(mentions)
                    if not bot_mentioned:
                        return
                    # Remove @mention text
                    for m in mentions:
                        text = text.replace(f"@{m.name}", "").strip()

            # DM policy
            if chat_type == "p2p":
                if self._dm_policy == "disabled":
                    return

            channel_msg = ChannelMessage(
                platform="feishu",
                chat_id=chat_id,
                chat_type="group" if chat_type == "group" else "dm",
                user_id=user_id,
                text=text,
                msg_id=msg_id,
            )

            # Dispatch to GatewayManager (async → schedule in event loop)
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._manager.dispatch(channel_msg), loop
                )
        except Exception as exc:
            log.error("[Feishu] Message handler error: %s", exc, exc_info=True)

    async def send_reply(self, chat_id: str, text: str, **kwargs: Any) -> bool:
        """Send a text reply to a Feishu chat."""
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
            )

            domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN
            client = lark.Client.builder() \
                .app_id(self._app_id) \
                .app_secret(self._app_secret) \
                .domain(domain) \
                .build()

            # Truncate if needed
            if len(text) > MAX_MSG_LEN:
                text = text[:MAX_MSG_LEN - 3] + "..."

            content = json.dumps({"text": text}, ensure_ascii=False)
            body = CreateMessageRequestBody.builder() \
                .receive_id(chat_id) \
                .msg_type("text") \
                .content(content) \
                .build()

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(body) \
                .build()

            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: client.im.v1.message.create(request)  # type: ignore[union-attr]
            )

            if not response.success():
                log.error("[Feishu] Send failed: %s %s", response.code, response.msg)
                return False
            return True

        except Exception as exc:
            log.error("[Feishu] send_reply error: %s", exc, exc_info=True)
            return False

    async def disconnect(self) -> None:
        self._running = False
        if self._ws_client:
            try:
                self._ws_client.stop()
            except Exception:
                pass
        log.info("[Feishu] Disconnected")

    @classmethod
    async def probe_bot(cls, app_id: str, app_secret: str, domain: str = "feishu") -> dict | None:
        """Verify credentials and return bot info. Used by setup wizard."""
        try:
            import lark_oapi as lark
            from lark_oapi.api.application.v6 import GetBotInfoRequest  # type: ignore[import]

            lark_domain = lark.LARK_DOMAIN if domain == "lark" else lark.FEISHU_DOMAIN
            client = lark.Client.builder() \
                .app_id(app_id) \
                .app_secret(app_secret) \
                .domain(lark_domain) \
                .build()

            req = GetBotInfoRequest.builder().build()
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None, lambda: client.application.v6.bot.get(req)  # type: ignore[attr-defined]
            )

            if resp.success() and resp.data and resp.data.bot:
                return {
                    "bot_name": getattr(resp.data.bot, "app_name", ""),
                    "open_id": getattr(resp.data.bot, "open_id", ""),
                }
            return None
        except Exception as exc:
            log.debug("[Feishu] probe_bot error: %s", exc)
            return None
