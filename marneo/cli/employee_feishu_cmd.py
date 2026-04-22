# marneo/cli/employee_feishu_cmd.py
"""marneo employee feishu — per-employee Feishu Bot setup."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
employee_feishu_app = typer.Typer(help="员工飞书 Bot 配置。")


@employee_feishu_app.command("setup")
def cmd_setup(
    name: str = typer.Argument(..., help="员工名称"),
) -> None:
    """为员工配置专属飞书 Bot（向导模式）。"""
    from prompt_toolkit import prompt as pt_prompt
    from marneo.employee.profile import load_profile
    from marneo.employee.feishu_config import (
        EmployeeFeishuConfig, save_feishu_config, load_feishu_config
    )

    profile = load_profile(name)
    if not profile:
        console.print(f"[red]员工 '{name}' 不存在。运行 marneo hire 招聘。[/red]")
        raise typer.Exit(1)

    console.print()
    console.print(Panel(
        f"[bold #FF6611]为 {name} 配置飞书 Bot[/bold #FF6611]\n\n"
        "1. 前往 [link]https://open.feishu.cn/[/link] 创建应用\n"
        "2. 开启「机器人」能力\n"
        "3. 复制 App ID 和 App Secret",
        border_style="#FF6611", padding=(1, 2),
    ))

    existing = load_feishu_config(name)
    if existing and existing.is_complete:
        console.print(f"[green]✓ {name} 已配置飞书 Bot[/green]")
        try:
            ans = pt_prompt("  重新配置？(y/N) ").strip().lower()
        except KeyboardInterrupt:
            return
        if ans not in ("y", "yes"):
            return

    try:
        app_id = pt_prompt("  App ID: ").strip()
        if not app_id:
            console.print("[yellow]已跳过。[/yellow]")
            return
        app_secret = pt_prompt("  App Secret: ", is_password=True).strip()
        if not app_secret:
            console.print("[yellow]已跳过。[/yellow]")
            return
    except KeyboardInterrupt:
        console.print("\n[dim]已取消。[/dim]")
        return

    # Domain selection
    from marneo.tui.select_ui import radiolist
    domain_idx = radiolist(
        "域名：",
        ["feishu（国内，open.feishu.cn）", "lark（海外，open.larksuite.com）"],
        default=0,
    )
    domain = "lark" if domain_idx == 1 else "feishu"

    # Verify and get bot open_id
    console.print("\n[dim]验证凭证...[/dim]")
    bot_open_id = ""
    try:
        import asyncio
        from marneo.gateway.adapters.feishu import FeishuChannelAdapter
        from marneo.gateway.manager import GatewayManager
        info = asyncio.run(FeishuChannelAdapter(GatewayManager()).probe_bot(
            app_id, app_secret, domain
        ))
        if info:
            bot_open_id = info.get("open_id", "")
            console.print(f"[green]✓ 验证成功 — Bot: {info.get('bot_name', '未知')}[/green]")
        else:
            console.print("[yellow]⚠ 无法验证，配置继续保存。[/yellow]")
    except Exception:
        console.print("[yellow]⚠ 验证跳过。[/yellow]")

    # Optional team chat ID
    try:
        team_chat_id = pt_prompt(
            "  团队协作群 ID（可选，用于多员工协作，直接回车跳过）: "
        ).strip()
    except KeyboardInterrupt:
        team_chat_id = ""

    config = EmployeeFeishuConfig(
        employee_name=name,
        app_id=app_id,
        app_secret=app_secret,
        domain=domain,
        bot_open_id=bot_open_id,
        team_chat_id=team_chat_id,
    )
    path = save_feishu_config(config)

    console.print()
    console.print(Panel(
        f"[bold #FF6611]{name} 的飞书 Bot 已配置！[/bold #FF6611]\n\n"
        f"  App ID：[dim]{app_id}[/dim]\n"
        f"  域名：{domain}\n"
        f"  配置文件：[dim]{path}[/dim]\n\n"
        "运行 [bold]marneo gateway start[/bold] 启动网关。",
        border_style="#FFD700", padding=(1, 2),
    ))


@employee_feishu_app.command("status")
def cmd_status(
    name: str = typer.Argument(..., help="员工名称"),
) -> None:
    """查看员工飞书 Bot 配置状态。"""
    from marneo.employee.feishu_config import load_feishu_config, has_feishu_config

    if not has_feishu_config(name):
        console.print(f"[dim]{name} 未配置飞书 Bot。运行 marneo employee feishu setup {name}[/dim]")
        return

    cfg = load_feishu_config(name)
    if not cfg:
        return

    console.print()
    console.print(Panel(
        f"[bold cyan]{name}[/bold cyan] 飞书 Bot 配置\n\n"
        f"  App ID：[dim]{cfg.app_id}[/dim]\n"
        f"  域名：{cfg.domain}\n"
        f"  Bot OpenID：[dim]{cfg.bot_open_id or '—'}[/dim]\n"
        f"  团队群 ID：[dim]{cfg.team_chat_id or '—'}[/dim]",
        border_style="#00FFCC", padding=(1, 2),
    ))
