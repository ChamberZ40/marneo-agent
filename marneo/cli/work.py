# marneo/cli/work.py
"""marneo work — chat with employee. (stub, full implementation in Task 6)"""
from __future__ import annotations
import typer
from rich.console import Console
console = Console()
work_app = typer.Typer(help="与数字员工对话。", invoke_without_command=True)

@work_app.callback(invoke_without_command=True)
def cmd_work(
    employee: str | None = typer.Option(None, "--employee", "-e"),
) -> None:
    """与数字员工对话。"""
    console.print("[dim]marneo work — 完整实现即将到来[/dim]")
