# marneo/cli/employee_feishu_cmd.py
"""marneo employee feishu — per-employee Feishu Bot setup."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()
employee_feishu_app = typer.Typer(help="员工飞书 Bot 配置。")


# ---------------------------------------------------------------------------
# QR-code one-click app registration
# ---------------------------------------------------------------------------

def _register_app_via_qr() -> dict | None:
    """Run lark.register_app() with interactive QR prompts.

    Returns the result dict on success, or None on failure / cancellation.
    Keys: client_id, client_secret, user_info (optional).
    """
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
    warnings.filterwarnings("ignore", message=".*pkg_resources.*")

    import lark_oapi as lark
    from lark_oapi.scene.registration import (
        RegisterAppError,
        AppAccessDeniedError,
        AppExpiredError,
    )

    def _on_qr_code(info: dict) -> None:
        url = info.get("url", "")
        expire_in = info.get("expire_in", 600)
        console.print()
        console.print(Panel(
            "[bold]请在飞书中打开以下链接（或扫码）完成授权：[/bold]\n\n"
            f"  [link]{url}[/link]\n\n"
            f"[dim]等待扫码... (有效期 {expire_in} 秒)[/dim]",
            border_style="#FF6611", padding=(1, 2),
        ))

    def _on_status_change(info: dict) -> None:
        status = info.get("status", "")
        if status == "polling":
            pass  # silent — avoid noisy repeated output
        elif status == "domain_switched":
            console.print("[dim]  已切换到 Lark 域名。[/dim]")
        elif status == "slow_down":
            console.print("[dim]  服务器要求降速，自动调整中...[/dim]")
        else:
            console.print(f"[dim]  状态: {status}[/dim]")

    try:
        result = lark.register_app(
            on_qr_code=_on_qr_code,
            on_status_change=_on_status_change,
        )
        return result
    except AppAccessDeniedError:
        console.print("[red]授权被拒绝。请在飞书中确认授权。[/red]")
        return None
    except AppExpiredError:
        console.print("[red]二维码已过期，请重试。[/red]")
        return None
    except RegisterAppError as exc:
        console.print(f"[red]注册失败: {exc}[/red]")
        return None
    except KeyboardInterrupt:
        console.print("\n[dim]已取消。[/dim]")
        return None


def _detect_domain_from_user_info(user_info: dict | None) -> str:
    """Detect 'feishu' or 'lark' from register_app user_info."""
    if not user_info:
        return "feishu"
    brand = user_info.get("tenant_brand", "")
    return "lark" if brand == "lark" else "feishu"


# ---------------------------------------------------------------------------
# Manual input flow (extracted from original cmd_setup)
# ---------------------------------------------------------------------------

def _manual_setup(name: str) -> tuple[str, str, str, str] | None:
    """Run the manual App ID / Secret input flow.

    Returns (app_id, app_secret, domain, bot_open_id) or None on cancel.
    """
    from prompt_toolkit import prompt as pt_prompt
    from marneo.tui.select_ui import radiolist

    try:
        app_id = pt_prompt("  App ID: ").strip()
        if not app_id:
            console.print("[yellow]已跳过。[/yellow]")
            return None
        app_secret = pt_prompt("  App Secret: ", is_password=True).strip()
        if not app_secret:
            console.print("[yellow]已跳过。[/yellow]")
            return None
    except KeyboardInterrupt:
        console.print("\n[dim]已取消。[/dim]")
        return None

    # Domain selection
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
        import warnings
        warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
        warnings.filterwarnings("ignore", message=".*pkg_resources.*")
        from marneo.gateway.adapters.feishu import FeishuChannelAdapter
        from marneo.gateway.manager import GatewayManager
        info = asyncio.run(FeishuChannelAdapter(GatewayManager()).probe_bot(
            app_id, app_secret, domain
        ))
        if info:
            bot_open_id = info.get("open_id", "")
            console.print(f"[green]验证成功 -- Bot: {info.get('bot_name', '未知')}[/green]")
        else:
            console.print("[yellow]无法验证，配置继续保存。[/yellow]")
    except Exception:
        console.print("[yellow]验证跳过。[/yellow]")

    return app_id, app_secret, domain, bot_open_id


# ---------------------------------------------------------------------------
# Main setup command
# ---------------------------------------------------------------------------

@employee_feishu_app.command("setup")
def cmd_setup(
    name: str = typer.Argument(..., help="员工名称"),
) -> None:
    """为员工配置专属飞书 Bot（向导模式）。"""
    from prompt_toolkit import prompt as pt_prompt
    from marneo.tui.select_ui import radiolist
    from marneo.employee.profile import load_profile
    from marneo.employee.feishu_config import (
        EmployeeFeishuConfig, save_feishu_config, load_feishu_config,
    )

    profile = load_profile(name)
    if not profile:
        console.print(f"[red]员工 '{name}' 不存在。运行 marneo hire 招聘。[/red]")
        raise typer.Exit(1)

    console.print()
    console.print(Panel(
        f"[bold #FF6611]为 {name} 配置飞书 Bot[/bold #FF6611]\n\n"
        "选择一种方式创建并绑定飞书应用。",
        border_style="#FF6611", padding=(1, 2),
    ))

    existing = load_feishu_config(name)
    if existing and existing.is_complete:
        console.print(f"[green]{name} 已配置飞书 Bot (App ID: {existing.app_id})[/green]")
        try:
            ans = pt_prompt("  重新配置？(y/N) ").strip().lower()
        except KeyboardInterrupt:
            return
        if ans not in ("y", "yes"):
            return

    # ── Choose config method ─────────────────────────────────────────
    method_idx = radiolist(
        "选择配置方式：",
        [
            "扫码一键创建（推荐 -- 自动创建飞书应用）",
            "手动输入 App ID / App Secret",
        ],
        default=0,
    )

    app_id = ""
    app_secret = ""
    domain = "feishu"
    bot_open_id = ""

    if method_idx == 0:
        # ── QR-code one-click flow ───────────────────────────────────
        result = _register_app_via_qr()
        if result is None:
            return

        app_id = result.get("client_id", "")
        app_secret = result.get("client_secret", "")
        user_info = result.get("user_info") or {}
        domain = _detect_domain_from_user_info(user_info)

        console.print()
        console.print(
            f"[bold green]飞书应用创建成功！[/bold green]\n"
            f"  App ID:  [dim]{app_id}[/dim]\n"
            f"  域名:    {domain}"
        )
    else:
        # ── Manual flow ──────────────────────────────────────────────
        console.print()
        console.print(Panel(
            "1. 前往 [link]https://open.feishu.cn/[/link] 创建应用\n"
            "2. 开启「机器人」能力\n"
            "3. 复制 App ID 和 App Secret",
            border_style="dim", padding=(1, 2),
        ))
        manual_result = _manual_setup(name)
        if manual_result is None:
            return
        app_id, app_secret, domain, bot_open_id = manual_result

    # ── Optional team chat ID ────────────────────────────────────────
    try:
        team_chat_id = pt_prompt(
            "  团队协作群 ID（可选，用于多员工协作，直接回车跳过）: "
        ).strip()
    except KeyboardInterrupt:
        team_chat_id = ""

    # ── Save ─────────────────────────────────────────────────────────
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
