# marneo/cli/setup_cmd.py
"""marneo setup — configure provider. (stub, full implementation in Task 4)"""
from __future__ import annotations
import typer
setup_app = typer.Typer(help="配置 Marneo。", invoke_without_command=True)

@setup_app.callback(invoke_without_command=True)
def setup_main(ctx: typer.Context) -> None:
    """配置 Marneo Provider。"""
    if ctx.invoked_subcommand is None:
        from rich.console import Console
        Console().print("[dim]marneo setup — 完整实现即将到来[/dim]")
