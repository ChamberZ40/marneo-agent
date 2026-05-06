# marneo/gateway/manager.py
from __future__ import annotations
import asyncio, logging, time
from collections import OrderedDict
from typing import Any
from marneo.gateway.base import BaseChannelAdapter, ChannelMessage
from marneo.gateway.session import SessionStore
from marneo.tools.registry import registry as _tool_registry

log = logging.getLogger(__name__)
DEDUP_TTL = 60
REPLY_TIMEOUT = 300
MAX_REPLY_LEN = 3000


class _Dedup:
    def __init__(self) -> None:
        self._cache: OrderedDict[str, float] = OrderedDict()

    def seen(self, msg_id: str) -> bool:
        if not msg_id:
            return False
        now = time.monotonic()
        if msg_id in self._cache:
            if now - self._cache[msg_id] < DEDUP_TTL:
                return True
            del self._cache[msg_id]
        self._cache[msg_id] = now
        self._cache.move_to_end(msg_id)
        if len(self._cache) > 2000:
            self._cache.popitem(last=False)
        return False


class GatewayManager:
    def __init__(self) -> None:
        self._adapters: dict[str, BaseChannelAdapter] = {}
        self._sessions = SessionStore()
        self._dedup = _Dedup()
        self._running = False

    def register(self, adapter: BaseChannelAdapter) -> None:
        self._adapters[adapter.platform] = adapter

    async def dispatch(self, msg: ChannelMessage) -> None:
        if msg.msg_id and self._dedup.seen(msg.msg_id):
            return
        if not msg.text.strip() and not msg.attachments:
            return
        engine, lock = await self._sessions.get_or_create(msg.platform, msg.chat_id)
        adapter = self._adapters.get(msg.platform)
        if not adapter:
            return
        async with lock:
            await self._process(msg, engine, adapter)

    async def _process(self, msg: ChannelMessage, engine: Any, adapter: BaseChannelAdapter) -> None:
        log.info("[msg:%s] Processing via %s", msg.msg_id[:12] if msg.msg_id else "?",
                 "streaming" if hasattr(adapter, "process_streaming") else "text")
        # Use streaming card if adapter supports it (Feishu with Card Kit)
        if hasattr(adapter, "process_streaming") and getattr(adapter, "_running", False):
            try:
                async with asyncio.timeout(REPLY_TIMEOUT):
                    await adapter.process_streaming(msg, engine, _tool_registry)
                return
            except TimeoutError:
                await adapter.send_reply(msg.chat_id, "处理超时，请重试。")
                return
            except Exception as e:
                log.error("[Gateway] Streaming process error: %s", e)
                # Don't fall through to text mode — card may already be visible
                return

        # Text fallback: collect all text events then send
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
            log.warning(
                "[Gateway] Empty reply from engine platform=%s chat_id=%s msg_id=%s",
                msg.platform,
                msg.chat_id,
                msg.msg_id or "",
            )
            reply = "模型没有返回内容，请重试。"
        while reply:
            chunk, reply = reply[:MAX_REPLY_LEN], reply[MAX_REPLY_LEN:]
            await adapter.send_reply(msg.chat_id, chunk, context_token=msg.context_token)

    async def start_all(self) -> None:
        # ── Per-employee Feishu bots ──────────────────────────────────────────
        try:
            from marneo.employee.feishu_config import list_configured_employees, load_feishu_config
            from marneo.gateway.adapters.feishu import FeishuChannelAdapter

            for emp_name in list_configured_employees():
                emp_cfg = load_feishu_config(emp_name)
                if not emp_cfg or not emp_cfg.is_complete:
                    continue
                # Create a dedicated adapter for this employee
                adapter = FeishuChannelAdapter(self, employee_name=emp_name)
                self.register(adapter)
                config = {
                    "app_id": emp_cfg.app_id,
                    "app_secret": emp_cfg.app_secret,
                    "domain": emp_cfg.domain,
                    "bot_open_id": emp_cfg.bot_open_id,
                    "bot_user_id": emp_cfg.bot_user_id,
                    "bot_name": emp_cfg.bot_name,
                    "dm_policy": emp_cfg.dm_policy,
                    "group_policy": emp_cfg.group_policy,
                    "enabled": True,
                }
                try:
                    ok = await adapter.connect(config)
                    log.info("[Gateway] employee %s feishu: %s", emp_name,
                             "connected" if ok else "failed")
                except Exception as e:
                    log.error("[Gateway] employee %s feishu error: %s", emp_name, e)
        except Exception as e:
            log.warning("[Gateway] employee feishu setup error: %s", e)

        # ── Global channel configs ────────────────────────────────────────────
        from marneo.gateway.config import load_channel_configs
        for platform, config in load_channel_configs().items():
            if not config.get("enabled", False):
                continue
            adapter = self._adapters.get(platform)
            if not adapter:
                continue
            try:
                ok = await adapter.connect(config)
                log.info("[Gateway] %s: %s", platform, "connected" if ok else "failed")
            except Exception as e:
                log.error("[Gateway] %s error: %s", platform, e)

    async def stop_all(self) -> None:
        for adapter in self._adapters.values():
            try:
                await adapter.disconnect()
            except Exception:
                pass

    @staticmethod
    def _mask_identifier(value: str, keep: int = 12) -> str:
        if not value:
            return ""
        if len(value) <= keep:
            return value
        return value[:keep] + "..."

    def _channel_health_detail(self, platform: str, adapter: BaseChannelAdapter) -> dict[str, Any]:
        last_event = getattr(adapter, "_last_event_time", 0) or 0
        ws_future = getattr(adapter, "_ws_future", None)
        ws_client = getattr(adapter, "_ws_client", None)
        conn = getattr(ws_client, "_conn", None) if ws_client is not None else None
        future_done = bool(ws_future.done()) if ws_future is not None and hasattr(ws_future, "done") else None
        connection_lost = None
        if hasattr(adapter, "_ws_connection_lost"):
            try:
                connection_lost = bool(adapter._ws_connection_lost())  # type: ignore[attr-defined]
            except Exception:
                connection_lost = None
        elif ws_client is not None:
            connection_lost = conn is None or bool(getattr(conn, "closed", False)) or getattr(conn, "close_code", None) is not None

        detail = {
            "platform": platform,
            "employee": getattr(adapter, "_employee_name", "") or None,
            "running": bool(adapter.is_running),
            "connection_mode": getattr(adapter, "_connection_mode", None),
            "domain": getattr(adapter, "_domain", None),
            "bot_name": getattr(adapter, "_bot_name", "") or None,
            "bot_open_id": self._mask_identifier(getattr(adapter, "_bot_open_id", "") or ""),
            "bot_user_id": self._mask_identifier(getattr(adapter, "_bot_user_id", "") or ""),
            "last_event_seconds_ago": int(time.monotonic() - last_event) if last_event > 0 else None,
            "pending_inbound": len(getattr(adapter, "_pending_inbound", []) or []),
            "pending_text_batches": len(getattr(adapter, "_pending_text_batches", {}) or {}),
            "ws": {
                "future_done": future_done,
                "client_present": ws_client is not None,
                "conn_present": conn is not None,
                "conn_closed": bool(getattr(conn, "closed", False)) if conn is not None else None,
                "conn_close_code": getattr(conn, "close_code", None) if conn is not None else None,
                "connection_lost": connection_lost,
            },
        }
        if hasattr(adapter, "card_action_metrics_snapshot"):
            try:
                detail["card_actions"] = adapter.card_action_metrics_snapshot()  # type: ignore[attr-defined]
            except Exception:
                detail["card_actions"] = {"error": "unavailable"}
        if hasattr(adapter, "pending_questions_snapshot"):
            try:
                detail["pending_questions"] = adapter.pending_questions_snapshot()  # type: ignore[attr-defined]
            except Exception:
                detail["pending_questions"] = {"error": "unavailable"}
        if hasattr(adapter, "ws_restart_status_snapshot"):
            try:
                detail["ws_restart"] = adapter.ws_restart_status_snapshot()  # type: ignore[attr-defined]
            except Exception:
                detail["ws_restart"] = {"error": "unavailable"}
        return detail

    def health_payload(self, start_time: float | None = None) -> dict[str, Any]:
        """Build the /health JSON payload; kept separate so tests don't need aiohttp."""
        start_time = start_time or time.time()
        connected = [p for p, a in self._adapters.items() if a.is_running]
        last_event = 0
        for adapter in self._adapters.values():
            t = getattr(adapter, "_last_event_time", 0) or 0
            if t > last_event:
                last_event = t
        return {
            "status": "ok",
            "uptime_seconds": int(time.time() - start_time),
            "sessions": self._sessions.active_count,
            "connected_channels": connected,
            "channels_detail": {
                platform: self._channel_health_detail(platform, adapter)
                for platform, adapter in self._adapters.items()
            },
            "tools": len(_tool_registry.get_definitions()),
            "last_event_seconds_ago": int(time.monotonic() - last_event) if last_event > 0 else None,
        }

    async def _start_health_server(self, port: int = 8765) -> None:
        """Start a lightweight HTTP health check server."""
        _start_time = time.time()

        try:
            from aiohttp import web

            async def health(request: web.Request) -> web.Response:
                import json
                return web.Response(
                    content_type="application/json",
                    text=json.dumps(self.health_payload(_start_time), ensure_ascii=False),
                )

            app = web.Application()
            app.router.add_get("/health", health)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            log.info("[Gateway] Health check: http://0.0.0.0:%d/health", port)
        except ImportError:
            log.debug("[Gateway] aiohttp not available, health check disabled")
        except Exception as e:
            log.warning("[Gateway] Health check server failed to start: %s", e)

    async def _session_cleanup_loop(self) -> None:
        """Periodically evict expired sessions to prevent memory leak."""
        while self._running:
            await asyncio.sleep(300)
            try:
                before = self._sessions.active_count
                self._sessions._evict()
                after = self._sessions.active_count
                evicted = before - after
                if evicted > 0:
                    log.info("[Gateway] Evicted %d expired sessions (%d active)", evicted, after)
            except Exception as exc:
                log.warning("[Gateway] Session cleanup error: %s", exc)

    async def run_forever(self) -> None:
        self._running = True
        await self.start_all()
        await self._start_health_server()
        asyncio.create_task(self._session_cleanup_loop())
        log.info("[Gateway] Running.")
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop_all()
