# marneo/gateway/session.py
from __future__ import annotations
import asyncio, logging, time
from typing import Any

log = logging.getLogger(__name__)
SESSION_TTL = 1800


class _Entry:
    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    def touch(self) -> None:
        self._last = time.monotonic()

    @property
    def expired(self) -> bool:
        return time.monotonic() - self._last > SESSION_TTL


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, platform: str, chat_id: str) -> tuple[Any, asyncio.Lock]:
        key = f"{platform}:{chat_id}"
        async with self._lock:
            self._evict()
            if key not in self._sessions:
                engine = await self._create_engine()
                self._sessions[key] = _Entry(engine)
                log.info("[Session] new %s", key)
            else:
                self._sessions[key].touch()
        entry = self._sessions[key]
        return entry.engine, entry._lock

    async def _create_engine(self) -> Any:
        from marneo.engine.chat import ChatSession
        return ChatSession(system_prompt=(
            "你是一名专注的数字员工，通过 IM 渠道与用户协作。保持专业、简洁的沟通风格。"
        ))

    def _evict(self) -> None:
        for k in [k for k, e in self._sessions.items() if e.expired]:
            del self._sessions[k]

    @property
    def active_count(self) -> int:
        return len(self._sessions)
