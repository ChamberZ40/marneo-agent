# marneo/cli/report_cmd.py
"""marneo report — view work reports."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()
report_app = typer.Typer(help="工作报告（日报/周报）。", invoke_without_command=True)


def _active_employee() -> str | None:
    from marneo.employee.profile import list_employees
    names = list_employees()
    return names[0] if names else None


@report_app.callback(invoke_without_command=True)
def report_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        cmd_daily()


@report_app.command("daily")
def cmd_daily(
    employee: str | None = typer.Option(None, "--employee", "-e"),
    push: bool = typer.Option(False, "--push", help="推送到 channel（Phase 4 实现）"),
) -> None:
    """查看今日工作日报。"""
    from marneo.employee.reports import get_daily_report
    from datetime import date

    name = employee or _active_employee()
    if not name:
        console.print("[dim]尚无员工。运行 marneo hire 招聘。[/dim]")
        return

    today = date.today().isoformat()
    report = get_daily_report(name)

    if not report:
        console.print(f"[dim]{name} 今日（{today}）暂无记录。[/dim]")
        return

    console.print()
    console.print(Panel(
        report,
        title=f"[bold #FFD700]📋 {name} 日报 {today}[/bold #FFD700]",
        border_style="#FFD700", padding=(1, 2),
    ))

    if push:
        from marneo.employee.report_push import push_report
        ok = push_report(report, name)
        if ok:
            console.print("[green]✓ 报告已推送[/green]")
        else:
            console.print("[yellow]⚠ 推送失败（运行 marneo report push-config 配置推送目标）[/yellow]")


@report_app.command("weekly")
def cmd_weekly(
    employee: str | None = typer.Option(None, "--employee", "-e"),
) -> None:
    """查看本周工作周报。"""
    from marneo.employee.reports import generate_weekly_summary

    name = employee or _active_employee()
    if not name:
        console.print("[dim]尚无员工。[/dim]")
        return

    summary = generate_weekly_summary(name)
    console.print()
    console.print(Panel(
        summary,
        title=f"[bold #FFD700]📊 {name} 周报[/bold #FFD700]",
        border_style="#FFD700", padding=(1, 2),
    ))


@report_app.command("history")
def cmd_history(
    employee: str | None = typer.Option(None, "--employee", "-e"),
    n: int = typer.Option(7, "-n", help="最近 N 天"),
) -> None:
    """列出最近的日报记录。"""
    from marneo.employee.reports import list_daily_dates, get_daily_report

    name = employee or _active_employee()
    if not name:
        return

    dates = list_daily_dates(name)[:n]
    if not dates:
        console.print("[dim]暂无记录。[/dim]")
        return

    for d in dates:
        report = get_daily_report(name, d)
        count = sum(1 for l in (report or "").splitlines() if l.startswith("- ["))
        console.print(f"  [bold #FFD700]{d}[/bold #FFD700]  [dim]{count} 条[/dim]")


@report_app.command("push-config")
def cmd_push_config(
    employee: str | None = typer.Option(None, "--employee", "-e"),
) -> None:
    """配置报告推送目标（平台 + chat ID）。"""
    from marneo.tui.select_ui import radiolist
    from marneo.employee.report_push import configure_push
    from prompt_toolkit import prompt as pt_prompt

    name = employee or _active_employee()
    if not name:
        console.print("[dim]尚无员工。[/dim]")
        return

    platforms = ["feishu", "wechat", "telegram", "discord"]
    idx = radiolist("推送平台：", platforms, default=0)
    platform = platforms[idx]

    try:
        chat_id = pt_prompt(f"  Chat ID（{platform} 的群/用户 ID）: ").strip()
        if not chat_id:
            return
    except KeyboardInterrupt:
        return

    configure_push(name, platform, chat_id)
    console.print(f"[green]✓ 推送配置已保存：{platform} → {chat_id}[/green]")
    console.print("[dim]运行 marneo report daily --push 测试推送[/dim]")
