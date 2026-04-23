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

        base = "你是一名专注的数字员工，通过 IM 渠道与用户协作。保持专业、简洁的沟通风格。"
        system = base

        # Load employee context for platforms like "feishu:GAI", "telegram:GAI"
        if ":" in platform:
            emp_name = platform.split(":", 1)[1]
            try:
                from marneo.employee.profile import load_profile
                from marneo.employee.growth import build_level_directive
                profile = load_profile(emp_name)
                if profile:
                    if profile.soul_path.exists():
                        soul = profile.soul_path.read_text(encoding="utf-8").strip()
                        system = f"{soul}\n\n{base}"
                    directive = build_level_directive(profile)
                    if directive:
                        system = f"{system}\n\n{directive}"
                    # Inject project context
                    try:
                        from marneo.project.workspace import get_employee_projects
                        projects = get_employee_projects(emp_name)
                        if projects:
                            parts: list[str] = []
                            for proj in projects:
                                parts.append(f"## 项目：{proj.name}")
                                if proj.description:
                                    parts.append(f"描述：{proj.description}")
                                if proj.goals:
                                    parts.append("目标：" + "、".join(proj.goals[:3]))
                                if proj.agent_path.exists():
                                    parts.append(proj.agent_path.read_text(encoding="utf-8").strip())
                            if parts:
                                system += "\n\n# 当前项目\n\n" + "\n\n".join(parts)
                    except Exception:
                        pass
            except Exception as e:
                log.warning("[Session] Failed to load employee context for %s: %s", emp_name, e)

        return ChatSession(system_prompt=system)

    def _evict(self) -> None:
        for k in [k for k, e in self._sessions.items() if e.expired]:
            del self._sessions[k]

    @property
    def active_count(self) -> int:
        return len(self._sessions)
