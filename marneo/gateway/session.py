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
                engine = await self._create_engine(platform)
                self._sessions[key] = _Entry(engine)
                log.info("[Session] new %s", key)
            else:
                self._sessions[key].touch()
        entry = self._sessions[key]
        return entry.engine, entry._lock

    async def _create_engine(self, platform: str = "") -> Any:
        from marneo.engine.chat import ChatSession

        base_system = "你是一名专注的数字员工，通过 IM 渠道与用户协作。保持专业、简洁的沟通风格。"

        if ":" in platform:
            emp_name = platform.split(":", 1)[1]
            try:
                from marneo.memory.session_memory import SessionMemory
                from marneo.employee.profile import load_profile
                from marneo.employee.growth import build_level_directive

                profile = load_profile(emp_name)
                soul = ""
                if profile:
                    if profile.soul_path.exists():
                        soul = profile.soul_path.read_text(encoding="utf-8").strip()
                    directive = build_level_directive(profile)
                    if directive:
                        soul = f"{soul}\n\n{directive}" if soul else directive

                sm = SessionMemory(emp_name, soul=soul)
                system_prompt = sm.build_system_prompt()
                engine = ChatSession(system_prompt=system_prompt)
                engine._session_memory = sm  # attach for use in dispatch
                return engine
            except Exception as e:
                log.warning("[Session] SessionMemory init failed for %s: %s", emp_name, e)

        return ChatSession(system_prompt=base_system)

    def _evict(self) -> None:
        for k in [k for k, e in self._sessions.items() if e.expired]:
            del self._sessions[k]

    @property
    def active_count(self) -> int:
        return len(self._sessions)
