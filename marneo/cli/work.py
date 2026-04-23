# marneo/cli/work.py
"""marneo work — chat with a digital employee."""
from __future__ import annotations

import asyncio
from typing import Any

import typer
from rich.console import Console

console = Console()
work_app = typer.Typer(help="与数字员工对话。", invoke_without_command=True)

_RST  = "\033[0m"
_PRI  = "\033[1;38;2;255;102;17m"
_DIM  = "\033[38;2;85;85;85m"
_GOLD = "\033[38;2;255;215;0m"


def _select_employee() -> str | None:
    """Select employee via curses UI. Returns name or None."""
    from marneo.employee.profile import list_employees
    names = list_employees()
    if not names:
        console.print("[dim]尚无员工。运行 marneo hire 招聘第一位。[/dim]")
        return None
    if len(names) == 1:
        return names[0]
    from marneo.tui.select_ui import radiolist
    idx = radiolist("选择员工：", names, default=0)
    return names[idx]


@work_app.callback(invoke_without_command=True)
def cmd_work(
    employee: str | None = typer.Option(None, "--employee", "-e", help="员工名称"),
) -> None:
    """与数字员工开始对话。"""
    from marneo.core.config import is_configured
    if not is_configured():
        console.print("[red]未配置 Provider。请先运行: marneo setup[/red]")
        raise typer.Exit(1)

    name = employee or _select_employee()
    if not name:
        raise typer.Exit(1)

    from marneo.tools.loader import load_all_tools
    load_all_tools()

    asyncio.run(_work_loop(name))


async def _run_with_team(
    text: str,
    team: Any,
    session: Any,
    tui: Any,
    display: Any,
) -> str:
    """Execute a task in team mode: split → parallel specialists → aggregate → display."""
    from marneo.collaboration.coordinator import run_team_session  # type: ignore[import]

    _PRI  = "\033[1;38;2;255;102;17m"
    _DIM  = "\033[38;2;85;85;85m"
    _RST  = "\033[0m"

    member_str = " + ".join(
        f"{m.employee}({m.role or '专员'})" for m in team.members
    )
    tui.print(f"\n  {_PRI}◆ 团队模式{_RST}  {_DIM}{member_str}{_RST}")

    async def _progress(msg: str) -> None:
        tui.print(f"  {_DIM}{msg}{_RST}")

    final_reply = await run_team_session(
        user_message=text,
        team_config=team,
        coordinator_engine=session,
        progress_cb=_progress,
    )

    if final_reply:
        display.reset()
        # Feed in chunks for markdown rendering
        for i in range(0, len(final_reply), 80):
            display.on_text(final_reply[i:i + 80])
        display.finish()

    return final_reply


async def _work_loop(employee_name: str) -> None:
    from marneo.engine.chat import ChatSession
    from marneo.tui.chat_tui import ChatTUI
    from marneo.employee.profile import load_profile, increment_conversation
    from marneo.employee.growth import should_level_up, next_level, build_level_directive, promote
    from marneo.employee.reports import append_daily_entry

    profile = load_profile(employee_name)

    # Build system prompt
    base_system = (
        f"你是 {employee_name}，一名专注的数字员工。"
        "帮助用户推进他们的项目目标。"
        "保持专业、高效的沟通风格。"
    )
    if profile:
        directive = build_level_directive(profile)
        if directive:
            base_system = f"{base_system}\n\n{directive}"
        if profile.soul_path.exists():
            soul = profile.soul_path.read_text(encoding="utf-8").strip()
            base_system = f"{soul}\n\n{base_system}"

    # Inject project context
    try:
        from marneo.project.workspace import get_employee_projects  # type: ignore[import]
        projects = get_employee_projects(employee_name)
        if projects:
            proj_parts: list[str] = []
            for proj in projects:
                proj_parts.append(f"## 项目：{proj.name}")
                if proj.description:
                    proj_parts.append(f"描述：{proj.description}")
                if proj.goals:
                    proj_parts.append("目标：" + "、".join(proj.goals[:3]))
                if proj.agent_path.exists():
                    proj_parts.append(proj.agent_path.read_text(encoding="utf-8").strip())
            if proj_parts:
                base_system += "\n\n# 当前项目\n\n" + "\n\n".join(proj_parts)
    except Exception:
        projects = []

    # Inject skills
    try:
        from marneo.project.skills import get_skills_context  # type: ignore[import]
        skills_ctx = get_skills_context(employee_name)
        if skills_ctx:
            base_system += "\n\n" + skills_ctx
    except Exception:
        pass

    tui = ChatTUI(employee_name=employee_name)
    display = tui.make_display()
    session = ChatSession(system_prompt=base_system)

    # ── Team detection ────────────────────────────────────────────────
    from marneo.collaboration.team import load_team_config  # type: ignore[import]
    from marneo.collaboration.coordinator import should_use_team  # type: ignore[import]
    from marneo.project.workspace import get_employee_projects  # type: ignore[import]

    def _get_coordinator_team() -> Any:
        """Return TeamConfig if this employee is a coordinator in a configured team."""
        try:
            for proj in get_employee_projects(employee_name):
                team = load_team_config(proj.name)
                if team and team.coordinator == employee_name and team.is_configured():
                    return team
        except Exception:
            pass
        return None

    _active_team = _get_coordinator_team()

    level_str = f"[{profile.level}]" if profile else ""
    proj_count = len(projects) if projects else 0
    proj_info = f"  {_DIM}{proj_count} 个项目{_RST}" if proj_count else ""
    welcome = (
        f"\n  {_PRI}◆ {employee_name}{level_str}{_RST}"
        f"{proj_info}"
        f"  {_DIM}/help · Ctrl+C 退出{_RST}\n"
    )

    _level_up_pending = False

    async def on_input(text: str) -> None:
        nonlocal _level_up_pending
        cmd = text.lower().strip()

        if cmd in ("/quit", "/exit", "/q"):
            tui.print(f"{_DIM}再见。{_RST}")
            tui._running = False
            if tui._app and tui._app.is_running:
                tui._app.exit()
            return
        if cmd == "/clear":
            session.clear()
            tui.print(f"{_DIM}对话已清除。{_RST}")
            return
        if cmd == "/help":
            tui.print(
                f"  {_PRI}命令{_RST}\n"
                f"  /clear   清除对话\n"
                f"  /quit    退出\n"
            )
            return
        if cmd in ("y", "yes") and _level_up_pending:
            old_lv, new_lv = promote(employee_name)
            if new_lv:
                tui.print(f"{_PRI}🎉 恭喜！{employee_name} 已晋升为 {new_lv}！{_RST}")
            _level_up_pending = False
            return

        tui.print(f"  {_DIM}You › {text}{_RST}")
        display.reset()

        # ── Team mode ─────────────────────────────────────────────────
        if _active_team:
            try:
                use_team = await should_use_team(text, len(_active_team.members))
            except Exception:
                use_team = False

            if use_team:
                team_reply = await _run_with_team(text, _active_team, session, tui, display)
                if team_reply:
                    try:
                        from marneo.employee.profile import increment_conversation  # type: ignore[import]
                        from marneo.employee.reports import append_daily_entry  # type: ignore[import]
                        increment_conversation(employee_name)
                        append_daily_entry(
                            employee_name,
                            f"[Team] {text[:40]} → {team_reply[:60].replace(chr(10), ' ')}",
                            tag="协作",
                        )
                    except Exception:
                        pass
                    return

        # ── Solo mode ─────────────────────────────────────────────────
        async for event in session.send(text):
            if event.type == "text":
                display.on_text(event.content)
            elif event.type == "thinking":
                display.on_thinking(event.content)
            elif event.type == "error":
                display.on_error(event.content)

        reply = display.finish()

        # Post-turn tracking
        try:
            updated = increment_conversation(employee_name)
            if reply.strip():
                summary = reply.strip()[:60].replace("\n", " ")
                append_daily_entry(
                    employee_name,
                    f"Q: {text[:40]} → {summary}",
                    tag="对话"
                )
                # Auto-learn skill (junior/intern employees only)
                try:
                    from marneo.employee.skill_learner import maybe_save_skill  # type: ignore[import]
                    insight = maybe_save_skill(employee_name, text, reply)
                    if insight:
                        tui.print(f"\n{_DIM}💡 已提炼新技能：{insight[:40]}{_RST}")
                except Exception:
                    pass
            if updated and should_level_up(updated) and not _level_up_pending:
                nxt = next_level(updated.level)
                if nxt:
                    _level_up_pending = True
                    tui.print(
                        f"\n{_GOLD}---\n"
                        f"{employee_name} 申请升级到 {nxt}（在职 {updated.level_conversations} 次对话）\n"
                        f"输入 y 确认晋升{_RST}"
                    )
        except Exception:
            pass

    await tui.run(on_input, welcome=welcome)
