# marneo/gateway/adapters/feishu.py
"""Feishu/Lark channel adapter — production-grade.

Architecture ported from hermes-agent + openclaw:
- WebSocket long connection via lark-oapi (Hermes WS protocol)
- Per-chat serial processing (openclaw createChatQueue)
- Pending-inbound queue for startup/reconnect windows
- Reaction lifecycle: DONE on start → remove on success, CrossMark on fail
- Disk-persistent dedup across restarts
- Reply fallback when reply target withdrawn (codes 230011/231003)
- Bot identity hydration before WS start
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from marneo.gateway.base import BaseChannelAdapter, ChannelMessage
from marneo.gateway.adapters.feishu_streaming import FeishuStreamingCard

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — mirroring hermes-agent / openclaw
# ---------------------------------------------------------------------------

MAX_MSG_LEN = 4000          # practical Feishu per-message text limit
_DEDUP_TTL = 86400          # 24 h — matches openclaw
_DEDUP_CACHE_SIZE = 2048

# Detect markdown formatting — ported from hermes-agent
_MARKDOWN_HINT_RE = re.compile(
    r"(^#{1,6}\s)|(^\s*[-*]\s)|(^\s*\d+\.\s)|(^\s*---+\s*$)|(```)|(`[^`\n]+`)"
    r"|(\*\*[^*\n].+?\*\*)|(~~[^~\n].+?~~)|(\*[^*\n]+\*)|(\[[^\]]+\]\([^)]+\))|(^>\s)",
    re.MULTILINE,
)
_MARKDOWN_FENCE_OPEN_RE = re.compile(r"^```([^\n`]*)\s*$")
_MARKDOWN_FENCE_CLOSE_RE = re.compile(r"^```\s*$")


def _build_post_payload(content: str) -> str:
    """Build Feishu post payload with markdown rows (hermes-agent pattern).

    Splits at fenced code blocks so prose + code both render correctly.
    """
    rows: list[list[dict]] = []
    if "```" not in content:
        rows = [[{"tag": "md", "text": content}]]
    else:
        current: list[str] = []
        in_code = False

        def _flush() -> None:
            nonlocal current
            seg = "\n".join(current)
            if seg.strip():
                rows.append([{"tag": "md", "text": seg}])
            current = []

        for line in content.splitlines():
            stripped = line.strip()
            is_fence = bool(
                _MARKDOWN_FENCE_CLOSE_RE.match(stripped) if in_code
                else _MARKDOWN_FENCE_OPEN_RE.match(stripped)
            )
            if is_fence:
                if not in_code:
                    _flush()
                current.append(line)
                in_code = not in_code
                if not in_code:
                    _flush()
                continue
            current.append(line)
        _flush()

    if not rows:
        rows = [[{"tag": "md", "text": content}]]

    return json.dumps({"zh_cn": {"content": rows}}, ensure_ascii=False)


def _outbound_msg_type_and_payload(text: str) -> tuple[str, str]:
    """Return (msg_type, payload_json) — post for markdown, text for plain."""
    if _MARKDOWN_HINT_RE.search(text):
        return "post", _build_post_payload(text)
    return "text", json.dumps({"text": text}, ensure_ascii=False)


def _format_tool_trace(trace: list[dict]) -> str:
    """Format tool call trace for display in the streaming card."""
    lines = ["⏳ **工具调用中...**\n"]
    for t in trace:
        emoji = "✅" if t.get("done") else "🔧"
        name = t["name"]
        status = "完成" if t.get("done") else "执行中..."
        lines.append(f"{emoji} **{name}** — {status}")
    return "\n".join(lines)


_REACTION_IN_PROGRESS = "SaluteFace"  # "致敬" badge while processing
_REACTION_FAILURE = "CrossMark"    # ✗ on error
_REACTION_CACHE_SIZE = 1024        # LRU cap for (msg_id → reaction_id)
_PENDING_INBOUND_MAX = 1000        # cap pending queue; drop oldest beyond
_PENDING_DRAIN_POLL = 0.25         # seconds between drain loop polls
_PENDING_DRAIN_MAX_WAIT = 120.0    # give up after 2 min
_REPLY_FALLBACK_CODES = frozenset({230011, 231003})  # withdrawn/missing


# ---------------------------------------------------------------------------
# Patch lark-oapi SDK: route CARD messages through event handler
# The SDK silently drops MessageType.CARD (line 24-25 of _handle_data_frame).
# This module-level patch replaces the class method ONCE at import time.
# ---------------------------------------------------------------------------

def _patch_lark_oapi_card_handling() -> None:
    """Monkey-patch Client._handle_data_frame to handle CARD same as EVENT.

    This is the Python equivalent of openclaw-lark's lark-client.js line 344
    patch. Kept out of default import-time execution; the Feishu WebSocket
    startup path enables it explicitly so CARD callbacks are routable at runtime.
    """
    try:
        from lark_oapi.ws import Client
        from lark_oapi.ws.enum import MessageType

        import base64 as _b64
        import http as _http
        import time as _time
        from lark_oapi.ws.model import Response
        from lark_oapi.core import JSON as _JSON

        # Store original for reference
        _original = Client._handle_data_frame

        async def _fixed_handle_data_frame(self: Any, frame: Any) -> None:
            """_handle_data_frame with CARD support (patches the silent `return`)."""
            hs = frame.headers
            # Re-use SDK's internal helpers
            msg_id = ""
            trace_id = ""
            sum_ = "1"
            seq = "0"
            type_ = ""
            for h in hs:
                if h.key == "message_id":
                    msg_id = h.value
                elif h.key == "trace_id":
                    trace_id = h.value
                elif h.key == "sum":
                    sum_ = h.value
                elif h.key == "seq":
                    seq = h.value
                elif h.key == "type":
                    type_ = h.value

            pl = frame.payload
            if int(sum_) > 1:
                pl = self._combine(msg_id, int(sum_), int(seq), pl)
                if pl is None:
                    return

            message_type = MessageType(type_)

            resp = Response(code=_http.HTTPStatus.OK)
            try:
                start = int(round(_time.time() * 1000))
                if message_type == MessageType.EVENT:
                    result = self._event_handler.do_without_validation(pl)
                elif message_type == MessageType.CARD:
                    # THIS IS THE FIX: treat CARD same as EVENT
                    result = self._event_handler.do_without_validation(pl)
                else:
                    return
                end = int(round(_time.time() * 1000))
                header = hs.add()
                header.key = "biz_rt"
                header.value = str(end - start)
                if result is not None:
                    resp.data = _b64.b64encode(_JSON.marshal(result).encode("utf-8"))
            except Exception as e:
                log.error("[Feishu] handle message failed: type=%s, msg_id=%s, err=%s",
                          type_, msg_id, e)
                resp = Response(code=_http.HTTPStatus.INTERNAL_SERVER_ERROR)

            frame.payload = _JSON.marshal(resp).encode("utf-8")
            await self._write_message(frame.SerializeToString())

        Client._handle_data_frame = _fixed_handle_data_frame
        log.info("[Feishu] Patched lark-oapi Client._handle_data_frame for CARD support")
    except Exception as exc:
        log.warning("[Feishu] Failed to patch lark-oapi CARD handling: %s", exc)


def _feishu_card_ws_patch_enabled() -> bool:
    """Return True only when the risky lark-oapi CARD monkey patch is explicitly enabled."""
    return os.getenv("MARNEO_FEISHU_ENABLE_CARD_WS_PATCH", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# Apply optional patch only when explicitly requested.
# Default stays unpatched because the global SDK monkey patch can break normal
# message delivery even when it only changes the CARD branch.
if _feishu_card_ws_patch_enabled():
    _patch_lark_oapi_card_handling()


# ---------------------------------------------------------------------------
# _run_feishu_ws_client — hermes pattern
# ---------------------------------------------------------------------------

def _run_feishu_ws_client(app_id: str, app_secret: str, domain: Any,
                          handler: Any, on_ready: Any) -> None:
    """Run lark-oapi WS client in executor thread.

    Hermes pattern:
    - auto_reconnect=False — SDK reconnect causes "different loop" crashes
    - Client created inside thread — asyncio.Lock() binds to thread loop
    - When start() exits (connection lost), thread simply returns
    - Adapter watchdog detects death → kills thread → creates brand new one
    """
    import lark_oapi.ws.client as ws_client_module
    from lark_oapi.ws import Client as FeishuWSClient

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ws_client_module.loop = loop

    ws_client = FeishuWSClient(
        app_id=app_id,
        app_secret=app_secret,
        event_handler=handler,
        domain=domain,
        auto_reconnect=False,  # CRITICAL: disable SDK reconnect (hermes pattern)
    )
    # TODO: CARD callback routing — need to investigate why patching
    # _handle_data_frame breaks message delivery even when only touching CARD branch
    on_ready(ws_client, loop)

    try:
        ws_client.start()
    except Exception as exc:
        log.error("[Feishu] WS client exited: %s", exc)
    finally:
        # Clean up loop
        try:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        try:
            loop.stop()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass
        log.info("[Feishu] WS thread exited cleanly")


# ---------------------------------------------------------------------------
# Disk-persistent deduplication (matches openclaw 24-h TTL)
# ---------------------------------------------------------------------------

class MessageDeduplicator:
    """Persist seen message IDs to disk to survive restarts."""

    def __init__(self, app_id: str) -> None:
        from marneo.core.paths import get_marneo_dir
        self._path = get_marneo_dir() / "feishu" / f"dedup_{app_id}.json"
        self._path.parent.mkdir(exist_ok=True)
        self._seen: dict[str, float] = self._load()
        self._lock = threading.Lock()

    def _load(self) -> dict[str, float]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text())
            now = time.time()
            return {k: v for k, v in data.items() if now - v < _DEDUP_TTL}
        except Exception as exc:
            log.warning("[Feishu] Dedup load error: %s", exc)
            return {}

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(self._seen))
        except Exception as exc:
            log.warning("[Feishu] Dedup save error: %s", exc)

    def seen(self, msg_id: str) -> bool:
        """Return True if already processed; record and return False otherwise."""
        now = time.time()
        with self._lock:
            self._seen = {k: v for k, v in self._seen.items() if now - v < _DEDUP_TTL}
            if len(self._seen) > _DEDUP_CACHE_SIZE:
                oldest = sorted(self._seen, key=lambda k: self._seen[k])
                for k in oldest[:len(self._seen) - _DEDUP_CACHE_SIZE]:
                    del self._seen[k]
            if msg_id in self._seen:
                return True
            self._seen[msg_id] = now
            self._save()
            return False


# ---------------------------------------------------------------------------
# Main adapter
# ---------------------------------------------------------------------------

class FeishuChannelAdapter(BaseChannelAdapter):
    """Feishu/Lark adapter — WebSocket (default) or Webhook."""

    def __init__(self, manager: Any, employee_name: str = "") -> None:
        platform = f"feishu:{employee_name}" if employee_name else "feishu"
        super().__init__(platform)
        self._manager = manager
        self._employee_name = employee_name

        # Config
        self._app_id = ""
        self._app_secret = ""
        self._domain = "feishu"
        self._connection_mode = "websocket"
        self._dm_policy = "open"
        self._group_policy = "at_only"
        self._allowed_users: list[str] = []
        self._bot_open_id = ""
        self._bot_user_id = ""
        self._bot_name = ""

        # WS state
        self._ws_client: Any = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_future: Any = None
        self._ws_started_time: float = 0
        self._config: dict[str, Any] = {}

        # Main loop — captured at connect() time for thread-safe dispatch
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Dedup
        self._dedup: Optional[MessageDeduplicator] = None

        # Per-chat serial locks (openclaw createChatQueue)
        self._chat_locks: dict[str, asyncio.Lock] = {}
        self._chat_locks_meta: threading.Lock = threading.Lock()

        # Sender name cache: open_id → display_name (persistent for session lifetime)
        self._sender_name_cache: dict[str, str] = {}

        # Pending inbound queue (hermes-agent pattern)
        self._pending_inbound: list[Any] = []
        self._pending_inbound_lock = threading.Lock()
        self._pending_drain_scheduled = False

        # Reaction tracking: msg_id → reaction_id (for deletion)
        self._processing_reactions: OrderedDict[str, str] = OrderedDict()

        # Watchdog: track last event time for stale-connection detection
        self._last_event_time: float = 0
        self._watchdog_task: Optional[asyncio.Task] = None

    # -------------------------------------------------------------------------
    # Validation & connect
    # -------------------------------------------------------------------------

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
        try:
            import lark_oapi  # noqa: F401
        except ImportError:
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
        # Pre-populate bot identity from config (hydration fills gaps later)
        self._bot_open_id = config.get("bot_open_id", "") or self._bot_open_id
        self._bot_user_id = config.get("bot_user_id", "") or self._bot_user_id
        self._bot_name = config.get("bot_name", "") or self._bot_name
        self._loop = asyncio.get_running_loop()
        self._dedup = MessageDeduplicator(self._app_id)

        try:
            # Hydrate bot identity first so @-mention detection works
            await self._hydrate_bot_identity()

            if self._connection_mode == "webhook":
                await self._start_webhook()
            else:
                await self._start_websocket()

            self._running = True
            # Start watchdog for stale-connection detection
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
            log.info("[Feishu] Connected (domain=%s mode=%s employee=%s)",
                     self._domain, self._connection_mode, self._employee_name or "—")
            return True
        except Exception as exc:
            log.error("[Feishu] Connect failed: %s", exc, exc_info=True)
            return False

    # -------------------------------------------------------------------------
    # WS watchdog — restart if no events for threshold period
    # -------------------------------------------------------------------------

    def _should_restart_ws(self, threshold: float = 300) -> bool:
        """Check if WS should be restarted due to inactivity (testable sync helper)."""
        if self._last_event_time == 0:
            return False  # never received, still starting up
        return time.monotonic() - self._last_event_time > threshold

    def _ws_connection_lost(self, startup_grace: float = 30) -> bool:
        """Detect lark-oapi receive-loop death while Client.start() still blocks.

        The SDK starts _receive_message_loop as a background task and then blocks
        forever in _select().  If the receive task exits, _disconnect() clears
        client._conn, but the executor future can stay alive.  Treat that as a
        dead WS after a short grace window for initial _connect().
        """
        ws_client = self._ws_client
        if ws_client is None:
            return False

        started = self._ws_started_time
        if started and time.monotonic() - started < startup_grace:
            return False

        conn = getattr(ws_client, "_conn", None)
        if conn is None:
            return True
        if getattr(conn, "closed", False):
            return True
        if getattr(conn, "close_code", None) is not None:
            return True
        return False

    async def _watchdog_loop(self) -> None:
        """Periodically check for stale WS connection and FULL restart if needed.

        Hermes pattern: don't rely on SDK auto_reconnect.
        Kill the entire WS thread + Client, then create brand new ones.
        Also detects when the WS thread has exited (connection lost).
        """
        while self._running:
            await asyncio.sleep(60)
            if not self._running:
                break

            # Check 1: WS thread died (connection lost, start() returned)
            ws_thread_dead = (
                self._ws_future is not None
                and self._ws_future.done()
            )

            # Check 2: lark-oapi receive task died but Client.start() is still blocked
            ws_connection_lost = self._ws_connection_lost()

            # Check 3: No events for threshold period
            stale = self._should_restart_ws()

            if ws_thread_dead or ws_connection_lost or stale:
                if ws_thread_dead:
                    reason = "WS thread exited"
                elif ws_connection_lost:
                    reason = "WS connection lost"
                else:
                    reason = "no events for 5m"
                log.warning("[Feishu] Watchdog: %s — full restart (hermes pattern)", reason)
                try:
                    # Kill everything
                    await self._kill_ws()
                    # Brief pause before reconnecting
                    await asyncio.sleep(2)
                    # Brand new Client + thread
                    await self._start_websocket()
                    self._running = True
                    self._last_event_time = time.monotonic()
                    log.info("[Feishu] Watchdog: reconnected successfully")
                except Exception as exc:
                    log.error("[Feishu] Watchdog restart failed: %s", exc)
                    # Wait before next attempt
                    await asyncio.sleep(30)

    async def _kill_ws(self) -> None:
        """Kill WS client and thread completely (hermes _disable_websocket_auto_reconnect pattern)."""
        ws_client = self._ws_client
        ws_loop = self._ws_loop

        if ws_client is not None:
            try:
                setattr(ws_client, "_auto_reconnect", False)
            except Exception:
                pass

            # lark-oapi keeps its websocket connection bound to the WS thread loop.
            # Do not await conn.close() directly on the gateway loop; that is the
            # exact cross-loop failure mode seen in gateway.log.  If the WS loop is
            # still alive, schedule close there; otherwise just drop the client and
            # let watchdog create a fresh thread/client.
            conn = getattr(ws_client, "_conn", None)
            if conn and ws_loop is not None and not ws_loop.is_closed():
                try:
                    close_result = conn.close()
                    if asyncio.iscoroutine(close_result):
                        close_future = asyncio.run_coroutine_threadsafe(close_result, ws_loop)
                        await asyncio.wait_for(asyncio.wrap_future(close_future), timeout=3)
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            self._ws_client = None
            self._ws_loop = None
            self._ws_started_time = 0

        if self._ws_future is not None:
            self._ws_future.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._ws_future), timeout=5)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._ws_future = None

    # -------------------------------------------------------------------------
    # Bot identity hydration (hermes-agent _hydrate_bot_identity)
    # -------------------------------------------------------------------------

    async def _hydrate_bot_identity(self) -> None:
        """Fetch bot identity via /bot/v3/info for mention filtering."""
        if self._bot_open_id and self._bot_user_id and self._bot_name:
            return
        try:
            import httpx
            base = "https://open.larksuite.com" if self._domain == "lark" else "https://open.feishu.cn"
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{base}/open-apis/auth/v3/app_access_token/internal",
                    json={"app_id": self._app_id, "app_secret": self._app_secret},
                )
                token = r.json().get("app_access_token") or r.json().get("tenant_access_token")
                if not token:
                    return
                r2 = await client.get(
                    f"{base}/open-apis/bot/v3/info",
                    headers={"Authorization": f"Bearer {token}"},
                )
                bot = r2.json().get("bot", {})
                self._bot_open_id = self._bot_open_id or bot.get("open_id", "")
                self._bot_user_id = self._bot_user_id or bot.get("user_id", "")
                self._bot_name = self._bot_name or bot.get("app_name", "") or bot.get("name", "")
                log.info(
                    "[Feishu] Bot identity: open_id=%s user_id=%s name=%s",
                    self._bot_open_id[:12] if self._bot_open_id else "none",
                    self._bot_user_id[:12] if self._bot_user_id else "none",
                    self._bot_name or "none",
                )
        except Exception as exc:
            log.warning("[Feishu] Failed to hydrate bot identity: %s", exc)

    # -------------------------------------------------------------------------
    # WebSocket startup (hermes-agent run_in_executor + ws_client_module.loop patch)
    # -------------------------------------------------------------------------

    async def _start_websocket(self) -> None:
        # lark-oapi's official WS client drops MessageType.CARD frames by default,
        # but our full _handle_data_frame monkey patch is risky and has been seen
        # to break normal message delivery.  Keep it opt-in until the CARD patch is
        # proven safe against text EVENT delivery.
        if _feishu_card_ws_patch_enabled():
            _patch_lark_oapi_card_handling()
        else:
            log.info("[Feishu] CARD WS monkey patch disabled; set MARNEO_FEISHU_ENABLE_CARD_WS_PATCH=1 to enable")

        import lark_oapi as lark

        lark_domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN

        # No-op handler to suppress lark-oapi "processor not found" ERROR logs
        _noop = lambda data: None

        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message_event)
            .register_p2_card_action_trigger(self._on_card_action)
            .register_p2_im_message_message_read_v1(_noop)
            .register_p2_im_message_reaction_created_v1(_noop)
            .register_p2_im_message_reaction_deleted_v1(_noop)
            .register_p2_im_chat_member_bot_added_v1(_noop)
            .register_p2_im_chat_member_bot_deleted_v1(_noop)
            .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(_noop)
            .register_p2_application_application_app_version_publish_apply_v6(_noop)
            .register_p2_application_application_app_version_publish_revoke_v6(_noop)
            .build()
        )

        # Callback to receive the WS client created inside the thread
        def _on_ws_ready(client: Any, loop: asyncio.AbstractEventLoop) -> None:
            self._ws_client = client
            self._ws_loop = loop

        main_loop = asyncio.get_running_loop()
        self._ws_started_time = time.monotonic()
        self._ws_future = main_loop.run_in_executor(
            None,
            _run_feishu_ws_client,
            self._app_id,
            self._app_secret,
            lark_domain,
            handler,
            _on_ws_ready,
        )

    # -------------------------------------------------------------------------
    # Webhook startup (aiohttp)
    # -------------------------------------------------------------------------

    async def _start_webhook(self) -> None:
        try:
            from aiohttp import web
        except ImportError:
            log.error("[Feishu] aiohttp required for webhook mode")
            raise

        host = self._config.get("webhook_host", "0.0.0.0")
        port = int(self._config.get("webhook_port", 8080))
        app = web.Application()
        app.router.add_post("/webhook/feishu", self._handle_webhook_request)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.web.TCPSite(runner, host, port)
        await site.start()
        log.info("[Feishu] Webhook listening on %s:%s", host, port)

    async def _handle_webhook_request(self, request: Any) -> Any:
        from aiohttp import web
        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="Invalid JSON")
        if body.get("type") == "url_verification":
            return web.json_response({"challenge": body.get("challenge", "")})
        event_type = str((body.get("header") or {}).get("event_type") or "")
        if event_type == "im.message.receive_v1":
            import types
            data = types.SimpleNamespace(**body)
            self._on_message_event(data)
        return web.json_response({"code": 0, "msg": "ok"})

    # -------------------------------------------------------------------------
    # Loop readiness check (hermes-agent _loop_accepts_callbacks)
    # -------------------------------------------------------------------------

    def _loop_accepts_callbacks(self, loop: Any) -> bool:
        return (
            loop is not None
            and not getattr(loop, "is_closed", lambda: False)()
            and getattr(loop, "is_running", lambda: False)()
        )

    # -------------------------------------------------------------------------
    # Pending inbound queue (hermes-agent pattern)
    # -------------------------------------------------------------------------

    def _enqueue_pending(self, data: Any) -> bool:
        """Queue event for replay when loop is not ready. Returns True → start drainer."""
        with self._pending_inbound_lock:
            if len(self._pending_inbound) >= _PENDING_INBOUND_MAX:
                self._pending_inbound.pop(0)
                log.warning("[Feishu] Pending queue full; dropped oldest event")
            self._pending_inbound.append(data)
            should_start = not self._pending_drain_scheduled
            if should_start:
                self._pending_drain_scheduled = True
        log.warning("[Feishu] Queued inbound event for replay (loop not ready, depth=%d)",
                    len(self._pending_inbound))
        return should_start

    def _drain_pending(self) -> None:
        """Replay queued events once the adapter loop is ready (daemon thread)."""
        waited = 0.0
        while True:
            if not self._running:
                with self._pending_inbound_lock:
                    n = len(self._pending_inbound)
                    self._pending_inbound.clear()
                if n:
                    log.warning("[Feishu] Dropped %d queued events during shutdown", n)
                return

            loop = self._loop
            if self._loop_accepts_callbacks(loop):
                with self._pending_inbound_lock:
                    batch = list(self._pending_inbound)
                    self._pending_inbound.clear()
                    self._pending_drain_scheduled = False

                for data in batch:
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self._handle_message_event_data(data), loop
                        )
                        future.add_done_callback(self._log_future_error)
                    except Exception as exc:
                        log.error("[Feishu] Failed to replay queued event: %s", exc)
                return

            waited += _PENDING_DRAIN_POLL
            if waited >= _PENDING_DRAIN_MAX_WAIT:
                with self._pending_inbound_lock:
                    self._pending_inbound.clear()
                    self._pending_drain_scheduled = False
                log.error("[Feishu] Loop never became ready; dropped pending inbound queue")
                return
            time.sleep(_PENDING_DRAIN_POLL)

    # -------------------------------------------------------------------------
    # Inbound event entry point (called from WS thread)
    # -------------------------------------------------------------------------

    def _on_message_event(self, data: Any) -> None:
        self._last_event_time = time.monotonic()
        loop = self._loop
        log.debug("[Feishu] _on_message_event: loop=%s accepts=%s",
                 "none" if loop is None else "ok",
                 self._loop_accepts_callbacks(loop))
        if not self._loop_accepts_callbacks(loop):
            if self._enqueue_pending(data):
                threading.Thread(
                    target=self._drain_pending,
                    daemon=True,
                    name="feishu-inbound-drainer",
                ).start()
            return
        future = asyncio.run_coroutine_threadsafe(
            self._handle_message_event_data(data), loop
        )
        future.add_done_callback(self._log_future_error)

    @staticmethod
    def _log_future_error(f: Any) -> None:
        try:
            exc = f.exception()
            if exc:
                log.error("[Feishu] Background error: %s", exc, exc_info=exc)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Message normalization & dispatch
    # -------------------------------------------------------------------------

    async def _handle_message_event_data(self, data: Any) -> None:
        try:
            msg_body = data.event.message
            sender = data.event.sender
        except Exception as exc:
            log.debug("[Feishu] Malformed event data: %s", exc)
            return

        msg_type = getattr(msg_body, "message_type", "")
        content_str = getattr(msg_body, "content", "") or "{}"
        chat_id = getattr(msg_body, "chat_id", "") or ""
        chat_type = getattr(msg_body, "chat_type", "p2p") or "p2p"
        msg_id = getattr(msg_body, "message_id", "") or ""
        sender_id = getattr(getattr(sender, "sender_id", None), "open_id", "") or ""

        # ── Fast sync checks BEFORE any async operation ──────────────────────
        # Dedup MUST be first: Feishu WS re-delivers events if previous
        # processing was still in an await (e.g. _resolve_sender_name).
        if self._dedup and msg_id and self._dedup.seen(msg_id):
            log.debug("[Feishu] Duplicate msg ignored: %s", msg_id)
            return

        # Drop self-sent messages (sync check, no API call needed)
        if self._is_self_sent_bot_message(sender):
            log.debug("[Feishu] Dropping self-sent bot event: %s", msg_id)
            return

        # Allowlist check
        if self._allowed_users and sender_id not in self._allowed_users:
            return

        log.info("[msg:%s] Processing message from %s in %s (chat_type=%s)",
                 msg_id[:12] if msg_id else "?", sender_id[:12] if sender_id else "?",
                 chat_id[:12] if chat_id else "?", chat_type)

        # ── Async operations after dedup gate ────────────────────────────────
        # Resolve sender display name (cached, no repeated API calls)
        sender_name = await self._resolve_sender_name(sender_id)

        try:
            content = json.loads(content_str)
        except Exception:
            content = {}

        # Parse text
        text = self._extract_text(msg_type, content, msg_body)
        if text is None:
            return  # unsupported type

        # Group policy — default at_only requires explicit @mention of this bot
        mentioned_others: list[dict] = []  # other users/bots mentioned in the message
        if chat_type == "group":
            mentions = getattr(msg_body, "mentions", []) or []
            if not self._should_accept_group_message(content_str, mentions):
                log.debug(
                    "[Feishu] Group msg dropped: policy=%s chat=%s bot_open_id=%s bot_user_id=%s mentions=%d",
                    self._group_policy,
                    chat_id[:12],
                    self._bot_open_id[:12] if self._bot_open_id else "none",
                    self._bot_user_id[:12] if self._bot_user_id else "none",
                    len(mentions),
                )
                return
            mentioned_others = self._collect_non_self_mentions(mentions)
            text = self._strip_feishu_mentions(text, mentions)

        if chat_type == "p2p" and self._dm_policy == "disabled":
            return

        # Download attachments for image/file messages (multimodal support)
        attachments: list[dict] = []
        if msg_type == "image":
            image_key = content.get("image_key", "")
            if image_key and msg_id:
                att_data, att_media_type, att_filename = await self._download_feishu_resource(
                    message_id=msg_id,
                    file_key=image_key,
                    resource_type="image",
                    fallback_filename=f"{image_key}.jpg",
                )
                if att_data:
                    attachments.append({
                        "data": att_data,
                        "media_type": att_media_type,
                        "filename": att_filename,
                    })
                else:
                    log.info("[Feishu] Image download failed for key=%s msg=%s", image_key, msg_id)

        elif msg_type == "file":
            file_key = content.get("file_key", "")
            file_name = content.get("file_name", "") or file_key
            if file_key and msg_id:
                att_data, att_media_type, att_filename = await self._download_feishu_resource(
                    message_id=msg_id,
                    file_key=file_key,
                    resource_type="file",
                    fallback_filename=file_name,
                )
                if att_data:
                    attachments.append({
                        "data": att_data,
                        "media_type": att_media_type,
                        "filename": att_filename,
                    })
                else:
                    log.info("[Feishu] File download failed for key=%s msg=%s", file_key, msg_id)

        # Allow messages that have attachments even when text is empty
        if not text.strip() and not attachments:
            return

        # Inject rich session context — openclaw pattern:
        # [timestamp] Feishu[type] | sender_name (open_id) [msg:msg_id] [chat:chat_id]
        import datetime as _dt
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        chat_label = "Feishu group" if chat_type == "group" else "Feishu DM"
        name_part = f"{sender_name} " if sender_name else ""
        context_prefix = (
            f"[{now}] {chat_label} | "
            f"{name_part}(open_id={sender_id}) "
            f"[msg:{msg_id}] [chat:{chat_id}]"
        )
        display_text = f"{context_prefix}\n{text}" if text.strip() else ""

        # Append other mentioned users/bots so LLM can @mention them
        if mentioned_others:
            mentions_info = ", ".join(
                f"{m['name']} (open_id={m['open_id']})" if m.get('name')
                else f"open_id={m['open_id']}"
                for m in mentioned_others
            )
            display_text += f"\n[群里还提到了: {mentions_info}]"

        channel_msg = ChannelMessage(
            platform=self.platform,
            chat_id=chat_id,
            chat_type="group" if chat_type == "group" else "dm",
            user_id=sender_id,
            user_name=sender_name,
            text=display_text,
            msg_id=msg_id,
            attachments=attachments,
        )

        # Per-chat serial lock (openclaw createChatQueue)
        chat_lock = self._get_chat_lock(chat_id)
        async with chat_lock:
            await self._dispatch_with_lifecycle(channel_msg, msg_id)

    def _extract_text(self, msg_type: str, content: dict, msg_body: Any) -> Optional[str]:
        """Return text string for supported message types, None for unsupported."""
        if msg_type == "text":
            return content.get("text", "").strip()
        if msg_type == "image":
            # Caption text if present; download happens in _handle_message_event_data
            return content.get("text", "").strip() or ""
        if msg_type == "file":
            return content.get("file_name", "") or content.get("file_key", "") or ""
        if msg_type in ("post", "rich_text"):
            # Flatten post content to plain text
            return self._flatten_post(content)
        return None  # unsupported

    def _flatten_post(self, content: dict) -> str:
        """Flatten Feishu post/rich_text to plain text (simplified)."""
        try:
            zh = content.get("zh_cn") or content.get("en_us") or {}
            parts: list[str] = []
            for row in zh.get("content", []):
                for elem in row:
                    tag = elem.get("tag", "")
                    if tag == "text":
                        parts.append(elem.get("text", ""))
                    elif tag == "a":
                        parts.append(elem.get("text", "") or elem.get("href", ""))
                    elif tag == "at":
                        parts.append(f"@{elem.get('user_name', '')}")
            return " ".join(p for p in parts if p).strip()
        except Exception:
            return "[富文本消息]"

    def _message_mentions_this_bot(self, mentions: list[Any]) -> bool:
        """Return True when a Feishu mention explicitly targets this bot.

        IDs are authoritative. Name fallback is only used when no comparable ID
        is present in the mention payload. If bot identity is unavailable, do
        not treat "any mention" as a match.
        """
        for mention in mentions or []:
            mention_id = getattr(mention, "id", None)
            mention_open_id = str(getattr(mention_id, "open_id", "") or "").strip()
            mention_user_id = str(getattr(mention_id, "user_id", "") or "").strip()
            mention_name = str(getattr(mention, "name", "") or "").strip()

            if mention_open_id and self._bot_open_id:
                if mention_open_id == self._bot_open_id:
                    return True
                continue
            if mention_user_id and self._bot_user_id:
                if mention_user_id == self._bot_user_id:
                    return True
                continue
            if self._bot_name and mention_name == self._bot_name:
                return True
        return False

    def _should_accept_group_message(self, raw_content: str, mentions: list[Any]) -> bool:
        """Apply Marneo's group policy before dispatching a group message."""
        policy = (self._group_policy or "at_only").strip().lower()
        if policy == "disabled":
            return False
        if policy == "open":
            return True
        if policy == "all_only":
            return "@_all" in (raw_content or "")
        if policy == "at_only":
            return self._message_mentions_this_bot(mentions)
        log.warning("[Feishu] Unknown group_policy=%r; falling back to at_only", self._group_policy)
        return self._message_mentions_this_bot(mentions)

    def _collect_non_self_mentions(self, mentions: list[Any]) -> list[dict[str, str]]:
        """Collect mentions that target other users/bots for LLM context."""
        others: list[dict[str, str]] = []
        for mention in mentions or []:
            mention_id = getattr(mention, "id", None)
            open_id = str(getattr(mention_id, "open_id", "") or "").strip()
            user_id = str(getattr(mention_id, "user_id", "") or "").strip()
            name = str(getattr(mention, "name", "") or "").strip()
            if self._bot_open_id and open_id == self._bot_open_id:
                continue
            if self._bot_user_id and user_id == self._bot_user_id:
                continue
            if open_id or user_id or name:
                item = {"name": name}
                if open_id:
                    item["open_id"] = open_id
                if user_id:
                    item["user_id"] = user_id
                others.append(item)
        return others

    @staticmethod
    def _strip_feishu_mentions(text: str, mentions: list[Any]) -> str:
        """Remove Feishu @mention display text/placeholders from message text."""
        cleaned = text or ""
        for mention in mentions or []:
            name = str(getattr(mention, "name", "") or "").strip()
            if name:
                cleaned = cleaned.replace(f"@{name}", "").strip()
        cleaned = re.sub(r"@_user_\d+", "", cleaned).strip()
        cleaned = cleaned.replace("@_all", "").strip()
        return cleaned

    def _is_self_sent_bot_message(self, sender: Any) -> bool:
        """Return True only for events emitted by THIS bot.

        Drop self-sent messages to prevent infinite loops, but allow other
        bots' messages through so multi-agent @mention collaboration works.
        """
        sender_type = str(getattr(sender, "sender_type", "") or "").strip().lower()
        if sender_type not in {"bot", "app"}:
            return False
        sender_id_obj = getattr(sender, "sender_id", None)
        sender_open_id = str(getattr(sender_id_obj, "open_id", "") or "").strip()
        sender_user_id = str(getattr(sender_id_obj, "user_id", "") or "").strip()
        if self._bot_open_id and sender_open_id == self._bot_open_id:
            return True
        if self._bot_user_id and sender_user_id == self._bot_user_id:
            return True
        return False

    def _get_chat_lock(self, chat_id: str) -> asyncio.Lock:
        """Get or create per-chat asyncio lock (like openclaw's createChatQueue)."""
        with self._chat_locks_meta:
            if chat_id not in self._chat_locks:
                self._chat_locks[chat_id] = asyncio.Lock()
            return self._chat_locks[chat_id]

    async def _resolve_sender_name(self, open_id: str) -> str:
        """Resolve open_id → display name, cached for session lifetime."""
        if not open_id or open_id == self._bot_open_id:
            return ""
        if open_id in self._sender_name_cache:
            return self._sender_name_cache[open_id]
        try:
            import httpx
            base = "https://open.larksuite.com" if self._domain == "lark" else "https://open.feishu.cn"
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.post(
                    f"{base}/open-apis/auth/v3/tenant_access_token/internal",
                    json={"app_id": self._app_id, "app_secret": self._app_secret},
                )
                token = r.json().get("tenant_access_token", "")
                if not token:
                    self._sender_name_cache[open_id] = ""
                    return ""
                r2 = await client.get(
                    f"{base}/open-apis/contact/v3/users/{open_id}",
                    params={"user_id_type": "open_id"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                data = r2.json()
                name = (data.get("data", {}).get("user", {}).get("name", "") or "").strip()
                self._sender_name_cache[open_id] = name
                if name:
                    log.debug("[Feishu] Resolved sender %s → %s", open_id[:12], name)
                return name
        except Exception as exc:
            log.debug("[Feishu] _resolve_sender_name failed for %s: %s", open_id[:12], exc)
            self._sender_name_cache[open_id] = ""
            return ""

    # -------------------------------------------------------------------------
    # Dispatch with reaction lifecycle
    # -------------------------------------------------------------------------

    async def _dispatch_with_lifecycle(self, msg: ChannelMessage, msg_id: str) -> None:
        """Wrap dispatch with processing reaction: add on start, remove/replace on finish."""
        reaction_id = await self._add_reaction(msg_id, _REACTION_IN_PROGRESS)
        if reaction_id:
            self._remember_reaction(msg_id, reaction_id)

        success = False
        try:
            await self._manager.dispatch(msg)
            success = True
        except Exception as exc:
            log.error("[Feishu] Dispatch error: %s", exc, exc_info=True)
        finally:
            await self._finish_reaction(msg_id, success)

    def _remember_reaction(self, msg_id: str, reaction_id: str) -> None:
        self._processing_reactions[msg_id] = reaction_id
        self._processing_reactions.move_to_end(msg_id)
        while len(self._processing_reactions) > _REACTION_CACHE_SIZE:
            self._processing_reactions.popitem(last=False)

    async def _finish_reaction(self, msg_id: str, success: bool) -> None:
        reaction_id = self._processing_reactions.pop(msg_id, None)
        if reaction_id:
            removed = await self._delete_reaction(msg_id, reaction_id)
            if not removed:
                # Can't remove — don't stack failure badge on top of stuck DONE badge
                return
        if not success:
            await self._add_reaction(msg_id, _REACTION_FAILURE)

    # -------------------------------------------------------------------------
    # Reactions — hermes-agent technique: reaction_type({"emoji_type": ...})
    # -------------------------------------------------------------------------

    def _build_lark_client(self) -> Any:
        import lark_oapi as lark
        lark_domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN
        return (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .domain(lark_domain)
            .build()
        )

    async def _download_feishu_resource(
        self,
        *,
        message_id: str,
        file_key: str,
        resource_type: str,
        fallback_filename: str = "",
    ) -> tuple[bytes, str, str]:
        """Download a Feishu message resource. Returns (data, media_type, filename).

        Ported from hermes-agent._download_feishu_message_resource.
        resource_type: "image", "file", "audio", "media"
        Returns (b"", "", "") on any failure.
        """
        import mimetypes as _mimetypes

        if not message_id or not file_key or not self._app_id:
            return b"", "", ""

        try:
            from lark_oapi.api.im.v1 import GetMessageResourceRequest

            client = self._build_lark_client()
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(file_key)
                .type(resource_type)
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message_resource.get, request)

            if not resp or not getattr(resp, "success", lambda: False)():
                log.debug(
                    "[Feishu] Resource download failed %s/%s: code=%s",
                    message_id, file_key, getattr(resp, "code", "?"),
                )
                return b"", "", ""

            # Read binary data (BytesIO.getvalue() or file-like .read())
            file_obj = getattr(resp, "file", None)
            if file_obj is None:
                return b"", "", ""
            data = bytes(file_obj.getvalue()) if hasattr(file_obj, "getvalue") else bytes(file_obj.read())
            if not data:
                return b"", "", ""

            # Detect media type from Content-Type header (hermes pattern)
            raw = getattr(resp, "raw", None)
            headers = getattr(raw, "headers", {}) or {}
            ct = str(
                headers.get("Content-Type") or headers.get("content-type") or ""
            ).split(";")[0].strip().lower()

            filename = getattr(resp, "file_name", None) or fallback_filename or file_key
            if not ct:
                ct = _mimetypes.guess_type(filename)[0] or "application/octet-stream"

            return data, ct, filename

        except Exception as exc:
            log.warning("[Feishu] _download_feishu_resource error: %s", exc)
            return b"", "", ""

    async def _add_reaction(self, msg_id: str, emoji_type: str) -> Optional[str]:
        """Add emoji reaction; return reaction_id or None."""
        if not msg_id or not self._app_id:
            return None
        try:
            from lark_oapi.api.im.v1 import (
                CreateMessageReactionRequest,
                CreateMessageReactionRequestBody,
            )
            client = self._build_lark_client()
            # Use dict for reaction_type — hermes-agent pattern (not .emoji() builder)
            body = (
                CreateMessageReactionRequestBody.builder()
                .reaction_type({"emoji_type": emoji_type})
                .build()
            )
            request = (
                CreateMessageReactionRequest.builder()
                .message_id(msg_id)
                .request_body(body)
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message_reaction.create, request)
            if resp and getattr(resp, "success", lambda: False)():
                data = getattr(resp, "data", None)
                return getattr(data, "reaction_id", None)
            log.debug("[Feishu] Add reaction %s rejected: code=%s", emoji_type,
                      getattr(resp, "code", None))
        except Exception as exc:
            log.warning("[Feishu] Add reaction %s error: %s", emoji_type, exc)
        return None

    async def _delete_reaction(self, msg_id: str, reaction_id: str) -> bool:
        """Delete a reaction by its reaction_id."""
        if not msg_id or not reaction_id:
            return False
        try:
            from lark_oapi.api.im.v1 import DeleteMessageReactionRequest
            client = self._build_lark_client()
            request = (
                DeleteMessageReactionRequest.builder()
                .message_id(msg_id)
                .reaction_id(reaction_id)
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message_reaction.delete, request)
            if resp and getattr(resp, "success", lambda: False)():
                return True
            log.debug("[Feishu] Delete reaction rejected: code=%s", getattr(resp, "code", None))
        except Exception as exc:
            log.warning("[Feishu] Delete reaction error: %s", exc)
        return False

    # -------------------------------------------------------------------------
    # Card action handler
    # -------------------------------------------------------------------------

    def _on_card_action(self, data: Any) -> Any:
        """Route card button clicks — resolve ask_user questions or dispatch as synthetic text."""
        try:
            from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
            # lark-oapi passes a P2CardActionTrigger wrapper whose real payload
            # is in `.event`; older tests / adapters may pass the event payload
            # directly.  Support both shapes.
            event = getattr(data, "event", None) or data
            action = getattr(event, "action", None) or {}
            value = getattr(action, "value", {}) or {}
            if value is None:
                value = {}
            operator = getattr(event, "operator", None)
            user_id = getattr(operator, "open_id", "") if operator else ""
            card_context = getattr(event, "context", None)
            chat_id = (
                getattr(event, "open_chat_id", "")
                or getattr(card_context, "open_chat_id", "")
                or ""
            )
            msg_id = (
                getattr(event, "open_message_id", "")
                or getattr(card_context, "open_message_id", "")
                or ""
            )

            # ── ask_user question resolution ────────────────────────────────
            if isinstance(value, dict) and value.get("marneo_question_id"):
                # Legacy button cards kept the question id and answer in value.
                marneo_question_id = str(value.get("marneo_question_id") or "")
                answer = str(value.get("answer", ""))
                from marneo.gateway.pending_questions import pending_question_store
                resolved = pending_question_store.resolve(marneo_question_id, answer)
                if resolved:
                    log.info("[Feishu] Card action resolved legacy question %s", marneo_question_id)
                    resp = P2CardActionTriggerResponse()
                    resp.toast = {"type": "info", "content": "已收到回复"}
                    return resp

            # Current ask_user cards are Feishu form-submit cards.  Their submit
            # button name is ask_user_submit_<question_id>; field values arrive in
            # action.form_value.  Some SDK versions omit button name, so fall back
            # to the single pending question in this chat.
            from marneo.gateway.pending_questions import (
                ACTION_SUBMIT,
                SUBMIT_BUTTON_PREFIX,
                find_question_by_chat,
                get_input_field_name,
                get_select_field_name,
                pending_question_store,
                read_form_multi_select,
                read_form_text_field,
            )

            action_name = str(getattr(action, "name", "") or "")
            form_value = getattr(action, "form_value", {}) or {}
            if isinstance(form_value, str):
                try:
                    form_value = json.loads(form_value)
                except Exception:
                    form_value = {}
            if not isinstance(form_value, dict):
                form_value = {}

            is_submit = action_name.startswith(SUBMIT_BUTTON_PREFIX) or action_name == ACTION_SUBMIT
            if is_submit or form_value:
                question_id = ""
                if action_name.startswith(SUBMIT_BUTTON_PREFIX):
                    question_id = action_name[len(SUBMIT_BUTTON_PREFIX):]
                ctx = None
                if question_id:
                    from marneo.gateway.pending_questions import get_pending_question
                    ctx = get_pending_question(question_id)
                if ctx is None:
                    ctx = find_question_by_chat(self._app_id, chat_id)
                if ctx is not None:
                    answers: dict[str, str] = {}
                    for i, q in enumerate(ctx.questions or []):
                        question_text = str(q.get("question") or q.get("header") or f"问题 {i + 1}")
                        if q.get("options"):
                            selected = read_form_multi_select(form_value, get_select_field_name(i))
                            answers[question_text] = ", ".join(selected) if selected else "(no answer)"
                        else:
                            answers[question_text] = read_form_text_field(form_value, get_input_field_name(i)) or "(no answer)"
                    pending_question_store.resolve(ctx.question_id, answers)
                    log.info("[Feishu] Card action resolved question %s", ctx.question_id)
                    resp = P2CardActionTriggerResponse()
                    resp.toast = {"type": "info", "content": "已收到回复"}
                    return resp

                # It was clearly an ask_user form submit, but no live pending
                # context exists (expired/already answered, or malformed context).
                # Do not fall through to generic command dispatch; that creates
                # a bogus empty-chat message and can trigger LLM work.
                log.info(
                    "[Feishu] Card action submit ignored: no pending question "
                    "(action=%s chat=%s msg=%s form_keys=%s)",
                    action_name or "—",
                    chat_id or "—",
                    msg_id or "—",
                    sorted(form_value.keys()),
                )
                resp = P2CardActionTriggerResponse()
                resp.toast = {"type": "warning", "content": "该问题已过期或已被回答"}
                return resp

            # ── Existing behavior: dispatch as synthetic text ────────────────
            cmd = value.get("command", str(value)) if isinstance(value, dict) else str(value)
            if cmd and self._loop and self._loop_accepts_callbacks(self._loop):
                channel_msg = ChannelMessage(
                    platform=self.platform,
                    chat_id=chat_id,
                    chat_type="dm",
                    user_id=user_id,
                    text=cmd,
                    msg_id=msg_id,
                )
                asyncio.run_coroutine_threadsafe(
                    self._manager.dispatch(channel_msg), self._loop
                )
            return P2CardActionTriggerResponse()
        except Exception as exc:
            log.warning("[Feishu] Card action handler error: %s", exc)
            return None

    # -------------------------------------------------------------------------
    # Streaming card dispatch (Task 2)
    # -------------------------------------------------------------------------

    async def process_streaming(
        self,
        msg: "ChannelMessage",
        engine: Any,
        registry: Any,
    ) -> None:
        """Process message with streaming card — typewriter effect.

        Falls back to text send_reply if Card Kit card creation fails.
        """
        # Set ask_user context so the tool can send cards to this chat
        from marneo.tools.core.ask_user import ask_user_ctx, AskUserContext
        ctx_token = ask_user_ctx.set(AskUserContext(
            chat_id=msg.chat_id,
            adapter=self,
            sender_open_id=msg.user_id,
            msg_id=msg.msg_id,
            chat_type=msg.chat_type,
            thread_id=msg.context_token,
        ))

        # Check for pending text-reply questions before normal processing
        from marneo.gateway.pending_questions import pending_question_store
        if pending_question_store.has_pending_for_chat(msg.chat_id):
            # Strip the context prefix to get raw user text
            raw_text = msg.text
            # The context prefix ends with a newline before the user text
            if "\n" in raw_text:
                raw_text = raw_text.split("\n", 1)[-1].strip()
            resolved = pending_question_store.resolve_by_chat_text(msg.chat_id, raw_text)
            if resolved:
                log.info("[msg:%s] Resolved pending text-reply question", msg.msg_id[:12] if msg.msg_id else "?")
                ask_user_ctx.reset(ctx_token)
                return

        try:
            log.info("[msg:%s] Streaming started", msg.msg_id[:12] if msg.msg_id else "?")
            card = FeishuStreamingCard(
                app_id=self._app_id,
                app_secret=self._app_secret,
                domain=self._domain,
            )
            # Always reply to the original message — shows "回复 张子豪: ..." header
            card_started = await card.start(
                chat_id=msg.chat_id,
                reply_to_msg_id=msg.msg_id,
                sender_name=msg.user_name or "",
            )

            if not card_started:
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
            tool_trace: list[dict] = []  # tracks tool calls for display

            try:
                async for event in engine.send_with_tools(
                    msg.text, registry=registry, attachments=msg.attachments or None
                ):
                    if event.type == "text" and event.content:
                        # First text after tool calls — clear trace, show only final text
                        if tool_trace:
                            tool_trace.clear()
                        accumulated += event.content
                        await card.update(accumulated)
                    elif event.type == "tool_call":
                        # Tool is being called — the text so far is narration, not final answer.
                        # Reset accumulated so only post-tool text appears in the card.
                        accumulated = ""
                        # Parse tool name from event content (JSON: {"name": ..., ...})
                        tool_name = "tool"
                        try:
                            tc_data = json.loads(event.content)
                            tool_name = tc_data.get("name", "tool")
                        except Exception:
                            pass
                        tool_trace.append({"name": tool_name, "done": False})
                        await card.update(_format_tool_trace(tool_trace))
                    elif event.type == "tool_result":
                        log.debug("[Streaming] Tool result: %s", event.content[:100] if event.content else "")
                        # Mark the last pending tool as completed
                        for t in reversed(tool_trace):
                            if not t.get("done"):
                                t["done"] = True
                                break
                        if tool_trace:
                            await card.update(_format_tool_trace(tool_trace))
            except Exception as exc:
                log.error("[Streaming] LLM error during streaming: %s", exc)
                accumulated = accumulated or f"处理出错：{exc}"
            finally:
                await card.close(accumulated)
        finally:
            ask_user_ctx.reset(ctx_token)

    # -------------------------------------------------------------------------
    # Send reply — with reply fallback (openclaw WITHDRAWN_REPLY_ERROR_CODES)
    # -------------------------------------------------------------------------

    async def send_reply(
        self,
        chat_id: str,
        text: str,
        reply_to_msg_id: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """Send reply. Falls back to create if reply target is withdrawn."""
        if not text.strip():
            return True

        # Split long messages
        chunks = self._split_text(text)
        ok = True
        for chunk in chunks:
            sent = await self._send_one(chat_id, chunk, reply_to_msg_id=reply_to_msg_id)
            if not sent:
                ok = False
            # Only thread-reply the first chunk
            reply_to_msg_id = None
        return ok

    def _split_text(self, text: str) -> list[str]:
        """Split text into ≤MAX_MSG_LEN chunks, preferring line breaks."""
        if len(text) <= MAX_MSG_LEN:
            return [text]
        chunks = []
        while text:
            if len(text) <= MAX_MSG_LEN:
                chunks.append(text)
                break
            split_at = text.rfind("\n", 0, MAX_MSG_LEN)
            if split_at < MAX_MSG_LEN // 2:
                split_at = MAX_MSG_LEN
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        return chunks

    async def _send_one(
        self,
        chat_id: str,
        text: str,
        reply_to_msg_id: Optional[str] = None,
    ) -> bool:
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
                ReplyMessageRequest,
                ReplyMessageRequestBody,
            )
            client = self._build_lark_client()
            msg_type, content = _outbound_msg_type_and_payload(text)

            if reply_to_msg_id:
                # Try reply first
                body = (
                    ReplyMessageRequestBody.builder()
                    .msg_type(msg_type)
                    .content(content)
                    .build()
                )
                request = (
                    ReplyMessageRequest.builder()
                    .message_id(reply_to_msg_id)
                    .request_body(body)
                    .build()
                )
                resp = await asyncio.to_thread(client.im.v1.message.reply, request)
                if resp and getattr(resp, "success", lambda: False)():
                    log.debug("[Feishu] Reply sent to %s", reply_to_msg_id)
                    return True

                # Fallback if target withdrawn (openclaw WITHDRAWN_REPLY_ERROR_CODES)
                code = getattr(resp, "code", 0)
                if code in _REPLY_FALLBACK_CODES:
                    log.debug("[Feishu] Reply target withdrawn (code=%s), falling back to create", code)
                else:
                    log.error("[Feishu] Reply failed: code=%s msg=%s",
                              code, getattr(resp, "msg", None))
                    return False

            # Create (direct or fallback)
            body = (
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type(msg_type)
                .content(content)
                .build()
            )
            request = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(body)
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message.create, request)
            if resp and getattr(resp, "success", lambda: False)():
                log.debug("[Feishu] Message sent to chat %s", chat_id)
                return True

            log.error("[Feishu] Send failed chat_id=%s code=%s msg=%s",
                      chat_id, getattr(resp, "code", None), getattr(resp, "msg", None))
            return False

        except Exception as exc:
            log.error("[Feishu] send_one error: %s", exc, exc_info=True)
            return False

    # -------------------------------------------------------------------------
    # Disconnect
    # -------------------------------------------------------------------------

    async def disconnect(self) -> None:
        self._running = False
        await self._kill_ws()
        log.info("[Feishu] Disconnected (employee=%s)", self._employee_name or "—")

    # -------------------------------------------------------------------------
    # Probe (used by setup wizard)
    # -------------------------------------------------------------------------

    @classmethod
    async def probe_bot(
        cls, app_id: str, app_secret: str, domain: str = "feishu"
    ) -> dict | None:
        """Verify credentials; return {bot_name, open_id} or None."""
        try:
            import httpx
            base = "https://open.larksuite.com" if domain == "lark" else "https://open.feishu.cn"
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{base}/open-apis/auth/v3/app_access_token/internal",
                    json={"app_id": app_id, "app_secret": app_secret},
                )
                data = r.json()
                token = data.get("app_access_token") or data.get("tenant_access_token")
                if not token:
                    log.debug("[Feishu] probe_bot: no token code=%s", data.get("code"))
                    return None
                r2 = await client.get(
                    f"{base}/open-apis/bot/v3/info",
                    headers={"Authorization": f"Bearer {token}"},
                )
                bot_data = r2.json()
                if bot_data.get("code") != 0:
                    log.debug("[Feishu] probe_bot: bot info error code=%s", bot_data.get("code"))
                    return None
                bot = bot_data.get("bot", {})
                return {"bot_name": bot.get("app_name", ""), "open_id": bot.get("open_id", "")}
        except Exception as exc:
            log.debug("[Feishu] probe_bot error: %s", exc)
            return None
