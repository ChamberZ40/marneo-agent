# marneo/gateway/manager.py
from __future__ import annotations
import asyncio, logging, time
from collections import OrderedDict
from typing import Any
from marneo.gateway.base import BaseChannelAdapter, ChannelMessage
from marneo.gateway.session import SessionStore

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
        if not msg.text.strip():
            return
        engine, lock = await self._sessions.get_or_create(msg.platform, msg.chat_id)
        adapter = self._adapters.get(msg.platform)
        if not adapter:
            return
        async with lock:
            await self._process(msg, engine, adapter)

    async def _process(self, msg: ChannelMessage, engine: Any, adapter: BaseChannelAdapter) -> None:
        parts: list[str] = []
        try:
            async with asyncio.timeout(REPLY_TIMEOUT):
                async for event in engine.send(msg.text):
                    if event.type == "text" and event.content:
                        parts.append(event.content)
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

    async def run_forever(self) -> None:
        self._running = True
        await self.start_all()
        log.info("[Gateway] Running.")
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop_all()
