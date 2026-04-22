# marneo/cli/app.py
"""Marneo CLI root — typer entry point."""
from __future__ import annotations

import typer
from rich.console import Console

from marneo import __version__

console = Console()

app = typer.Typer(
    name="marneo",
    help="Marneo — Project-focused digital employees",
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=False,
)


def _version_cb(value: bool) -> None:
    if value:
        console.print(f"[bold]marneo[/bold] v{__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-v",
        callback=_version_cb, is_eager=True,
        help="Show version.",
    ),
) -> None:
    """Marneo — Project-focused digital employees."""
    if ctx.invoked_subcommand is None:
        # No subcommand → enter work mode directly
        from marneo.cli.work import cmd_work
        cmd_work()


def _register_subcommands() -> None:
    from marneo.cli.setup_cmd import setup_app
    from marneo.cli.work import work_app
    from marneo.cli.hire_cmd import hire_app
    from marneo.cli.employees_cmd import employees_app
    from marneo.cli.report_cmd import report_app
    app.add_typer(setup_app, name="setup")
    app.add_typer(work_app, name="work")
    app.add_typer(hire_app, name="hire")
    app.add_typer(employees_app, name="employees")
    app.add_typer(report_app, name="report")


_register_subcommands()
