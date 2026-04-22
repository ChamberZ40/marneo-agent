# marneo/gateway/adapters/feishu.py
"""Feishu / Lark channel adapter — production-grade.

Uses lark-oapi WebSocket long connection (default) or aiohttp Webhook for
receiving events.  Uses lark-oapi REST API for sending replies.

Config fields:
  app_id         - Feishu app ID (from open.feishu.cn)
  app_secret     - Feishu app secret
  domain         - "feishu" (China) | "lark" (International), default "feishu"
  connection_mode- "websocket" (default) | "webhook"
  webhook_host   - host to bind webhook server, default "0.0.0.0"
  webhook_port   - port for webhook server, default 8080
  dm_policy      - "open" | "allowlist" | "disabled", default "open"
  group_policy   - "at_only" | "open" | "disabled", default "at_only"
  allowed_users  - list of open_ids allowed to trigger the bot; empty = no restriction
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
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


# ---------------------------------------------------------------------------
# Disk-persistent deduplication
# ---------------------------------------------------------------------------

class MessageDeduplicator:
    """Persist seen message IDs to disk to survive restarts."""

    def __init__(self, app_id: str) -> None:
        from marneo.core.paths import get_marneo_dir
        self._path = get_marneo_dir() / "feishu" / f"dedup_{app_id}.json"
        self._path.parent.mkdir(exist_ok=True)
        self._seen: dict[str, float] = self._load()
        self._ttl = 86400  # 24 hours

    def _load(self) -> dict[str, float]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text())
            now = time.time()
            # Clean expired on load
            return {k: v for k, v in data.items() if now - v < self._ttl}
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(self._seen))
        except Exception as exc:
            log.warning("[Feishu] Deduplicator save error: %s", exc)

    def seen(self, msg_id: str) -> bool:
        """Return True if msg_id was already processed; record and return False otherwise."""
        now = time.time()
        # Evict expired entries
        self._seen = {k: v for k, v in self._seen.items() if now - v < self._ttl}
        if msg_id in self._seen:
            return True
        self._seen[msg_id] = now
        self._save()
        return False


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class FeishuChannelAdapter(BaseChannelAdapter):
    """Feishu/Lark adapter — WebSocket (default) or Webhook connection mode."""

    def __init__(self, manager: Any) -> None:
        super().__init__("feishu")
        self._manager = manager
        self._app_id = ""
        self._app_secret = ""
        self._domain = "feishu"
        self._connection_mode = "websocket"
        self._dm_policy = "open"
        self._group_policy = "at_only"
        self._allowed_users: list[str] = []
        self._bot_open_id = ""
        self._ws_client: Any = None
        self._dedup: MessageDeduplicator | None = None
        self._config: dict[str, Any] = {}
        # Main event loop captured at connect() time for thread-safe dispatch
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def validate_config(self, config: dict[str, Any]) -> tuple[bool, str]:
        if not config.get("app_id"):
            return False, "app_id is required"
        if not config.get("app_secret"):
            return False, "app_secret is required"
        mode = config.get("connection_mode", "websocket")
        if mode not in ("websocket", "webhook"):
            return False, "connection_mode must be 'websocket' or 'webhook'"
        return True, ""

    async def connect(self, config: dict[str, Any]) -> bool:
        if not _check_feishu_available():
            log.error("[Feishu] lark-oapi is not installed")
            return False

        ok, err = self.validate_config(config)
        if not ok:
            log.error("[Feishu] Config error: %s", err)
            return False

        self._config = config
        self._app_id = config["app_id"]
        self._app_secret = config["app_secret"]
        self._domain = config.get("domain", "feishu")
        self._connection_mode = config.get("connection_mode", "websocket")
        self._dm_policy = config.get("dm_policy", "open")
        self._group_policy = config.get("group_policy", "at_only")
        self._allowed_users = config.get("allowed_users", [])
        self._main_loop = asyncio.get_event_loop()
        self._dedup = MessageDeduplicator(self._app_id)

        try:
            if self._connection_mode == "webhook":
                await self._start_webhook()
            else:
                await self._start_websocket()
            self._running = True
            log.info(
                "[Feishu] Connected (domain=%s mode=%s)",
                self._domain,
                self._connection_mode,
            )
            return True
        except Exception as exc:
            log.error("[Feishu] Connect failed: %s", exc, exc_info=True)
            return False

    # ------------------------------------------------------------------
    # WebSocket mode
    # ------------------------------------------------------------------

    async def _start_websocket(self) -> None:
        """Start lark-oapi WebSocket client in background thread."""
        import lark_oapi as lark
        from lark_oapi.ws import Client as FeishuWSClient

        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message_receive)
            .register_p2_card_action_trigger(self._on_card_action)
            .build()
        )

        domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN
        self._ws_client = FeishuWSClient(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=handler,
            domain=domain,
        )

        import threading

        def _run_ws() -> None:
            import asyncio as _asyncio
            new_loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(new_loop)
            try:
                self._ws_client.start()  # blocking synchronous call
            except Exception as exc:
                log.error("[Feishu] WS thread error: %s", exc)
            finally:
                try:
                    new_loop.close()
                except Exception:
                    pass

        self._ws_thread = threading.Thread(
            target=_run_ws, daemon=True, name="feishu-ws"
        )
        self._ws_thread.start()

    # ------------------------------------------------------------------
    # Webhook mode (stub — aiohttp server)
    # ------------------------------------------------------------------

    async def _start_webhook(self) -> None:
        """Start aiohttp webhook server (stub implementation)."""
        try:
            from aiohttp import web  # type: ignore[import]
        except ImportError:
            log.error("[Feishu] aiohttp is not installed; cannot use webhook mode")
            raise

        host = self._config.get("webhook_host", "0.0.0.0")
        port = int(self._config.get("webhook_port", 8080))

        app = web.Application()
        app.router.add_post("/webhook/feishu", self._handle_webhook_request)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        log.info("[Feishu] Webhook server listening on %s:%s", host, port)

    async def _handle_webhook_request(self, request: Any) -> Any:
        """Handle incoming Feishu webhook POST requests."""
        from aiohttp import web  # type: ignore[import]
        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="Invalid JSON")

        # URL verification challenge
        if body.get("type") == "url_verification":
            return web.json_response({"challenge": body.get("challenge", "")})

        # Dispatch event (simplified — real impl would parse event schema)
        log.debug("[Feishu] Webhook event received: %s", body.get("header", {}).get("event_type"))
        return web.json_response({"code": 0})

    # ------------------------------------------------------------------
    # Message handler
    # ------------------------------------------------------------------

    def _on_message_receive(self, data: Any) -> None:
        """Called by lark-oapi when a message arrives."""
        try:
            msg_body = data.event.message
            sender = data.event.sender

            msg_type = msg_body.message_type
            content = json.loads(msg_body.content or "{}")

            chat_id = msg_body.chat_id or ""
            chat_type = msg_body.chat_type or "p2p"
            user_id = sender.sender_id.open_id if sender.sender_id else ""
            msg_id = msg_body.message_id or ""

            # Allowlist check
            if self._allowed_users and user_id not in self._allowed_users:
                return

            # Deduplication
            if self._dedup and msg_id and self._dedup.seen(msg_id):
                log.debug("[Feishu] Duplicate message ignored: %s", msg_id)
                return

            # Parse text by message type
            if msg_type == "text":
                text = content.get("text", "").strip()
                if not text:
                    return
            elif msg_type == "image":
                image_key = content.get("image_key", "")
                text = f"[图片: {image_key}]"
            elif msg_type == "file":
                file_key = content.get("file_key", "")
                file_name = content.get("file_name", "")
                text = f"[文件: {file_name or file_key}]"
            else:
                return  # Unsupported message type

            # Group policy: only respond to @mentions
            if chat_type == "group":
                if self._group_policy == "disabled":
                    return
                if self._group_policy == "at_only":
                    mentions = msg_body.mentions or []
                    bot_mentioned = (
                        any(m.id.open_id == self._bot_open_id for m in mentions)
                        if self._bot_open_id
                        else bool(mentions)
                    )
                    if not bot_mentioned:
                        return
                    # Remove @mention text
                    if msg_type == "text":
                        for m in mentions:
                            text = text.replace(f"@{m.name}", "").strip()

            # DM policy
            if chat_type == "p2p" and self._dm_policy == "disabled":
                return

            # Reaction: mark as processing
            self._add_reaction(msg_id, "Awaiting")

            channel_msg = ChannelMessage(
                platform="feishu",
                chat_id=chat_id,
                chat_type="group" if chat_type == "group" else "dm",
                user_id=user_id,
                text=text,
                msg_id=msg_id,
            )

            loop = self._main_loop or asyncio.get_event_loop()
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self._dispatch_and_react(channel_msg, msg_id), loop
                )
                # Best-effort: log if dispatch scheduling fails
                future.add_done_callback(
                    lambda f: log.error("[Feishu] Dispatch error: %s", f.exception())
                    if f.exception()
                    else None
                )
        except Exception as exc:
            log.error("[Feishu] Message handler error: %s", exc, exc_info=True)

    async def _dispatch_and_react(self, msg: ChannelMessage, msg_id: str) -> None:
        """Dispatch message and update reaction on completion."""
        try:
            await self._manager.dispatch(msg)
            self._add_reaction(msg_id, "THUMBSUP")
        except Exception as exc:
            log.error("[Feishu] Dispatch failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Card action handler
    # ------------------------------------------------------------------

    def _on_card_action(self, data: Any) -> Any:
        """Handle card button click — route as text command."""
        try:
            action = data.action if hasattr(data, "action") else {}
            value = getattr(action, "value", {}) or {}
            cmd = value.get("command", str(value))

            operator = getattr(data, "operator", None)
            user_id = getattr(operator, "open_id", "") if operator else ""

            token = getattr(data, "open_message_id", "")

            msg = ChannelMessage(
                platform="feishu",
                chat_id=token or user_id,
                user_id=user_id,
                text=cmd,
                msg_id=f"card_{token}",
            )

            loop = self._main_loop or asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._manager.dispatch(msg), loop
                )
        except Exception as exc:
            log.error("[Feishu] Card action error: %s", exc)

        try:
            from lark_oapi.event.callback.model.p2_card_action_trigger import (
                P2CardActionTriggerResponse,
            )
            return P2CardActionTriggerResponse()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Reaction helpers
    # ------------------------------------------------------------------

    def _add_reaction(self, message_id: str, emoji: str) -> None:
        """Add emoji reaction to a message (non-blocking, best-effort)."""
        if not message_id or not self._app_id or not self._app_secret:
            return
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import (
                CreateMessageReactionRequest,
                CreateMessageReactionRequestBody,
                Emoji,
            )

            domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN
            client = (
                lark.Client.builder()
                .app_id(self._app_id)
                .app_secret(self._app_secret)
                .domain(domain)
                .build()
            )
            emoji_obj = Emoji.builder().emoji_type(emoji).build()
            body = (
                CreateMessageReactionRequestBody.builder().emoji(emoji_obj).build()
            )
            req = (
                CreateMessageReactionRequest.builder()
                .message_id(message_id)
                .request_body(body)
                .build()
            )
            client.im.v1.message_reaction.create(req)  # type: ignore[attr-defined]
        except Exception:
            pass  # Reactions are best-effort

    def _remove_reaction(self, message_id: str, emoji: str) -> None:
        """Remove a reaction (simplified: no-op — requires knowing reaction_id)."""
        pass

    # ------------------------------------------------------------------
    # Send reply
    # ------------------------------------------------------------------

    async def send_reply(self, chat_id: str, text: str, **kwargs: Any) -> bool:
        """Send a text reply to a Feishu chat."""
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
            )

            domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN
            client = (
                lark.Client.builder()
                .app_id(self._app_id)
                .app_secret(self._app_secret)
                .domain(domain)
                .build()
            )

            if len(text) > MAX_MSG_LEN:
                text = text[:MAX_MSG_LEN - 3] + "..."

            content = json.dumps({"text": text}, ensure_ascii=False)
            body = (
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(content)
                .build()
            )
            request = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(body)
                .build()
            )

            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.im.v1.message.create(request),  # type: ignore[union-attr]
            )

            if not response.success():
                log.error("[Feishu] Send failed: %s %s", response.code, response.msg)
                return False
            return True

        except Exception as exc:
            log.error("[Feishu] send_reply error: %s", exc, exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Disconnect
    # ------------------------------------------------------------------

    async def disconnect(self) -> None:
        self._running = False
        if self._ws_client:
            try:
                self._ws_client.stop()
            except Exception:
                pass
        log.info("[Feishu] Disconnected")

    # ------------------------------------------------------------------
    # Probe
    # ------------------------------------------------------------------

    @classmethod
    async def probe_bot(
        cls, app_id: str, app_secret: str, domain: str = "feishu"
    ) -> dict | None:
        """Verify credentials and return bot info. Used by setup wizard."""
        try:
            import lark_oapi as lark
            from lark_oapi.api.application.v6 import GetBotInfoRequest  # type: ignore[import]

            lark_domain = lark.LARK_DOMAIN if domain == "lark" else lark.FEISHU_DOMAIN
            client = (
                lark.Client.builder()
                .app_id(app_id)
                .app_secret(app_secret)
                .domain(lark_domain)
                .build()
            )

            req = GetBotInfoRequest.builder().build()
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: client.application.v6.bot.get(req),  # type: ignore[attr-defined]
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
