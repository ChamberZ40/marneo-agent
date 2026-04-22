# marneo/cli/employees_cmd.py
"""marneo employees — manage digital employees."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
employees_app = typer.Typer(help="数字员工管理。", invoke_without_command=True)


@employees_app.callback(invoke_without_command=True)
def employees_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        cmd_list()


@employees_app.command("list")
def cmd_list() -> None:
    """列出所有数字员工。"""
    from marneo.employee.profile import list_employees, load_profile
    from marneo.employee.growth import days_at_level

    names = list_employees()
    if not names:
        console.print("[dim]尚无员工。运行 marneo hire 招聘第一位。[/dim]")
        return

    t = Table(title="数字员工", show_header=True, header_style="bold #FFD700")
    t.add_column("名称", style="bold cyan")
    t.add_column("等级", style="#FFD700")
    t.add_column("在职天数", justify="right")
    t.add_column("本级对话", justify="right")
    t.add_column("总对话", justify="right")

    for name in names:
        p = load_profile(name)
        if p:
            t.add_row(name, p.level, str(days_at_level(p)),
                      str(p.level_conversations), str(p.total_conversations))

    console.print()
    console.print(t)


@employees_app.command("show")
def cmd_show(name: str = typer.Argument(..., help="员工名称")) -> None:
    """查看员工详情。"""
    from marneo.employee.profile import load_profile, LEVEL_ORDER
    from marneo.employee.growth import days_at_level, should_level_up, next_level, LEVELUP_THRESHOLDS

    p = load_profile(name)
    if not p:
        console.print(f"[red]员工 '{name}' 不存在。[/red]")
        raise typer.Exit(1)

    level_idx = LEVEL_ORDER.index(p.level) if p.level in LEVEL_ORDER else 0
    stars = "★" * (level_idx + 1) + "☆" * (len(LEVEL_ORDER) - level_idx - 1)

    console.print()
    console.print(Panel(
        f"[bold #FF6611]{p.name}[/bold #FF6611]  "
        f"[bold #FFD700]{p.level}[/bold #FFD700]  [dim]{stars}[/dim]\n\n"
        f"  性格：{p.personality or '—'}  领域：{p.domains or '—'}  风格：{p.style or '—'}\n"
        f"  在职：[bold]{days_at_level(p)}[/bold] 天  "
        f"本级对话：[bold]{p.level_conversations}[/bold]  "
        f"总对话：[bold]{p.total_conversations}[/bold]",
        title="[bold #FFD700]✦ 员工档案[/bold #FFD700]",
        border_style="#FF6611", padding=(1, 2),
    ))

    if p.soul_path.exists():
        soul = p.soul_path.read_text(encoding="utf-8").strip()
        console.print(Panel(soul, title="[dim]SOUL.md[/dim]",
                            border_style="#555555", padding=(1, 2)))

    nxt = next_level(p.level)
    if nxt and p.level in LEVELUP_THRESHOLDS:
        min_days, min_convs, min_skills = LEVELUP_THRESHOLDS[p.level]
        days = days_at_level(p)
        console.print(f"\n  [dim]升级进度 → {nxt}[/dim]")
        console.print(
            f"  天数：{days}/{min_days}  "
            f"对话：{p.level_conversations}/{min_convs}  "
            f"Skill：{p.level_skills}/{min_skills}"
        )
        if should_level_up(p):
            console.print(
                f"  [bold #00FFCC]✦ 升级条件已满足！[/bold #00FFCC]"
            )
    console.print()


@employees_app.command("fire")
def cmd_fire(name: str = typer.Argument(..., help="员工名称")) -> None:
    """解雇员工（删除档案）。"""
    import shutil
    from marneo.employee.profile import load_profile
    from prompt_toolkit import prompt as pt_prompt

    p = load_profile(name)
    if not p:
        console.print(f"[red]员工 '{name}' 不存在。[/red]")
        raise typer.Exit(1)

    try:
        confirm = pt_prompt(f"  确认解雇 {name}？(y/N) ").strip().lower()
    except KeyboardInterrupt:
        return

    if confirm not in ("y", "yes"):
        console.print("[dim]已取消。[/dim]")
        return

    shutil.rmtree(p.directory)
    console.print(f"[dim]{name} 已解雇。[/dim]")


from marneo.cli.employee_feishu_cmd import employee_feishu_app
employees_app.add_typer(employee_feishu_app, name="feishu")
