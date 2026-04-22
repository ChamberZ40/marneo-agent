# marneo/cli/status_cmd.py
"""marneo status — global system overview."""
from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def cmd_status() -> None:
    """显示全局状态：Provider、员工、项目、Gateway。"""
    from rich.table import Table
    from rich import box as rich_box
    from marneo.core.config import load_config
    from marneo.employee.profile import list_employees, load_profile
    from marneo.employee.growth import days_at_level
    from marneo.project.workspace import list_projects, get_employee_projects
    from marneo.gateway.config import load_channel_configs
    from marneo.cli.gateway_cmd import _read_pid

    console.print()

    # Provider
    cfg = load_config()
    if cfg.provider and cfg.provider.api_key:
        p_status = f"[green]✓[/green] {cfg.provider.id} / {cfg.provider.model}"
    else:
        p_status = "[red]✗ 未配置[/red]"
    console.print(f"  Provider:  {p_status}")

    # Gateway
    pid = _read_pid()
    gw_status = f"[green]🟢 运行中 (PID: {pid})[/green]" if pid else "[dim]⚪ 未启动[/dim]"
    console.print(f"  Gateway:   {gw_status}")
    channels = load_channel_configs()
    for platform, config in channels.items():
        enabled = "[green]✓[/green]" if config.get("enabled") else "[dim]○[/dim]"
        console.print(f"    {enabled} {platform}")

    # Employees
    console.print()
    employees = list_employees()
    if employees:
        t = Table(box=rich_box.SIMPLE, show_header=True, header_style="bold dim")
        t.add_column("员工", style="cyan")
        t.add_column("等级")
        t.add_column("在职天数", justify="right", style="dim")
        t.add_column("总对话", justify="right", style="dim")
        for name in employees:
            p = load_profile(name)
            if p:
                t.add_row(name, p.level, str(days_at_level(p)), str(p.total_conversations))
        console.print(t)
    else:
        console.print("  [dim]暂无员工。运行 marneo hire 招聘。[/dim]")

    # Projects
    proj_names = list_projects()
    if proj_names:
        console.print(f"  项目：{', '.join(proj_names)}")
    else:
        console.print("  [dim]暂无项目。运行 marneo projects new 创建。[/dim]")
    console.print()
