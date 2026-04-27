# marneo/gateway/session.py
from __future__ import annotations
import asyncio, datetime as _dt, logging, time
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
        from marneo.gateway.platform_hints import get_platform_hint

        platform_hint = get_platform_hint(platform)

        if ":" in platform:
            emp_name = platform.split(":", 1)[1]
            try:
                from marneo.memory.session_memory import SessionMemory
                from marneo.employee.profile import load_profile
                from marneo.employee.growth import build_level_directive

                profile = load_profile(emp_name)
                # Use display name from profile, fallback to directory name
                display_name = getattr(profile, 'name', emp_name) if profile else emp_name
                soul = f"Your name is {display_name} (id: {emp_name}).\n\n"
                if profile:
                    if profile.soul_path.exists():
                        soul += profile.soul_path.read_text(encoding="utf-8").strip()
                    directive = build_level_directive(profile)
                    if directive:
                        soul = f"{soul}\n\n{directive}"

                sm = SessionMemory(emp_name, soul=soul)
                system_prompt = sm.build_system_prompt()

                # Session startup context with platform-specific hints
                startup_ctx = (
                    f"Session started at {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
                    f"Employee: {display_name} (id: {emp_name}). "
                    f"{platform_hint} "
                    f"You have tools available: bash, read_file, write_file, edit_file, "
                    f"glob, grep, web_fetch, web_search, lark_cli, "
                    f"feishu_send_mention, feishu_search_user, feishu_create_doc. "
                    f"Use them when asked to do something."
                )
                if len(system_prompt) + len(startup_ctx) + 2 < sm._budget.system_prompt_max:
                    system_prompt = f"{system_prompt}\n\n{startup_ctx}"

                engine = ChatSession(system_prompt=system_prompt)
                engine._session_memory = sm  # attach for use in dispatch
                return engine
            except Exception as e:
                log.warning("[Session] SessionMemory init failed for %s: %s", emp_name, e)

        # Fallback: basic system prompt with platform hint
        base_system = (
            "You are a work-focused digital employee running inside Marneo. "
            "You are capable, direct, and action-oriented. "
            f"{platform_hint} "
            "Be concise. Report results, not intentions."
        )
        return ChatSession(system_prompt=base_system)

    def _evict(self) -> None:
        for k in [k for k, e in self._sessions.items() if e.expired]:
            del self._sessions[k]

    @property
    def active_count(self) -> int:
        return len(self._sessions)
