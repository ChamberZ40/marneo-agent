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
    if ctx.invoked_subcommand is not None:
        return

    from rich.console import Console
    from rich.table import Table
    from rich import box as rich_box

    console = Console()
    from marneo import __version__
    from marneo.core.config import is_configured
    from marneo.employee.profile import list_employees

    # ── First-run wizard ──────────────────────────────────────────────
    if not is_configured():
        from rich.panel import Panel
        console.print()
        console.print(Panel(
            f"[bold #FF6611]欢迎使用 Marneo v{__version__}[/bold #FF6611]\n\n"
            "新马，新征程。\n\n"
            "[dim]首次使用需要完成初始配置：[/dim]\n"
            "  1. 配置 LLM Provider → [bold]marneo setup[/bold]\n"
            "  2. 招聘第一位数字员工 → [bold]marneo hire[/bold]",
            border_style="#FF6611", padding=(1, 2),
        ))
        return

    employees = list_employees()
    if not employees:
        from rich.panel import Panel
        console.print()
        console.print(Panel(
            "[bold #FFD700]Provider 已配置，还没有员工。[/bold #FFD700]\n\n"
            "运行 [bold]marneo hire[/bold] 招聘第一位数字员工。",
            border_style="#FFD700", padding=(1, 1),
        ))
        return

    # ── Dashboard ─────────────────────────────────────────────────────
    from marneo.employee.profile import load_profile
    from marneo.employee.growth import days_at_level
    from marneo.project.workspace import get_employee_projects
    from marneo.gateway.config import load_channel_configs
    from marneo.cli.gateway_cmd import _read_pid

    console.print()
    console.print(f"[bold #FF6611]◆ Marneo[/bold #FF6611]  [dim]v{__version__}[/dim]")
    console.print()

    t = Table(box=rich_box.SIMPLE, show_header=True, header_style="bold")
    t.add_column("员工", style="bold cyan")
    t.add_column("等级", style="#FFD700")
    t.add_column("项目")
    t.add_column("在职天数", justify="right", style="dim")

    for name in employees:
        p = load_profile(name)
        if p:
            projs = get_employee_projects(name)
            t.add_row(
                name, p.level,
                ", ".join(proj.name for proj in projs[:2]) or "—",
                str(days_at_level(p)),
            )
    console.print(t)

    pid = _read_pid()
    gw = "[green]🟢 运行中[/green]" if pid else "[dim]⚪ 未启动[/dim]"
    channels = load_channel_configs()
    enabled_ch = [p for p, c in channels.items() if c.get("enabled")]
    ch_str = ", ".join(enabled_ch) if enabled_ch else "未配置"
    console.print(f"  网关：{gw}  渠道：[dim]{ch_str}[/dim]")
    console.print()
    console.print("  [dim]marneo work     开始工作[/dim]")
    console.print("  [dim]marneo status   查看详情[/dim]")
    console.print("  [dim]marneo hire     招聘员工[/dim]")
    console.print()


def _register_subcommands() -> None:
    from marneo.cli.setup_cmd import setup_app
    from marneo.cli.work import work_app
    from marneo.cli.hire_cmd import hire_app
    from marneo.cli.employees_cmd import employees_app
    from marneo.cli.report_cmd import report_app
    from marneo.cli.projects_cmd import projects_app, assign_app
    from marneo.cli.skills_cmd import skills_app
    from marneo.cli.gateway_cmd import gateway_app
    from marneo.cli.team_cmd import team_app
    from marneo.cli.memory_cmd import memory_app
    from marneo.cli.web_cmd import web_app
    app.add_typer(setup_app, name="setup")
    app.add_typer(work_app, name="work")
    app.add_typer(web_app, name="web")
    app.add_typer(hire_app, name="hire")
    app.add_typer(employees_app, name="employees")
    app.add_typer(report_app, name="report")
    app.add_typer(projects_app, name="projects")
    app.add_typer(assign_app, name="assign")
    app.add_typer(skills_app, name="skills")
    app.add_typer(gateway_app, name="gateway")
    app.add_typer(team_app, name="team")
    app.add_typer(memory_app, name="memory")

    from marneo.cli.status_cmd import cmd_status as _cmd_status

    @app.command("status")
    def _status_cmd() -> None:
        """显示全局状态。"""
        _cmd_status()


_register_subcommands()


if __name__ == "__main__":
    app()
