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
REPLY_TIMEOUT = 60
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
                # Fall through to text mode

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
            return
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

    async def _start_health_server(self, port: int = 8765) -> None:
        """Start a lightweight HTTP health check server."""
        import time
        _start_time = time.time()

        try:
            from aiohttp import web

            async def health(request: web.Request) -> web.Response:
                import json
                connected = [p for p, a in self._adapters.items() if a.is_running]
                return web.Response(
                    content_type="application/json",
                    text=json.dumps({
                        "status": "ok",
                        "uptime_seconds": int(time.time() - _start_time),
                        "sessions": self._sessions.active_count,
                        "connected_channels": connected,
                    }),
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

    async def run_forever(self) -> None:
        self._running = True
        await self.start_all()
        await self._start_health_server()
        log.info("[Gateway] Running.")
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop_all()
