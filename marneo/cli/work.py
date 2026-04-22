# marneo/cli/work.py
"""marneo work — chat with a digital employee."""
from __future__ import annotations

import asyncio

import typer
from rich.console import Console

console = Console()
work_app = typer.Typer(help="与数字员工对话。", invoke_without_command=True)

_RST = "\033[0m"
_PRI = "\033[1;38;2;255;102;17m"
_DIM = "\033[38;2;85;85;85m"


@work_app.callback(invoke_without_command=True)
def cmd_work(
    employee: str | None = typer.Option(None, "--employee", "-e", help="员工名称"),
) -> None:
    """与数字员工开始对话。"""
    from marneo.core.config import is_configured
    if not is_configured():
        console.print("[red]未配置 Provider。请先运行: marneo setup[/red]")
        raise typer.Exit(1)

    name = employee or "Marneo"
    asyncio.run(_work_loop(name))


async def _work_loop(employee_name: str) -> None:
    from marneo.engine.chat import ChatSession
    from marneo.tui.chat_tui import ChatTUI

    tui = ChatTUI(employee_name=employee_name)
    display = tui.make_display()
    session = ChatSession(
        system_prompt=(
            f"你是 {employee_name}，一名专注的数字员工。"
            "你的工作是帮助用户推进他们的项目目标。"
            "保持专业、高效、简洁的沟通风格。"
        )
    )

    welcome = (
        f"\n  {_PRI}◆ {employee_name}{_RST}"
        f"  {_DIM}就位。  /help 帮助  Ctrl+C 退出{_RST}\n"
    )

    async def on_input(text: str) -> None:
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

        tui.print(f"  {_DIM}You › {text}{_RST}")
        display.reset()

        async for event in session.send(text):
            if event.type == "text":
                display.on_text(event.content)
            elif event.type == "thinking":
                display.on_thinking(event.content)
            elif event.type == "error":
                display.on_error(event.content)

        display.finish()

    await tui.run(on_input, welcome=welcome)
