# marneo/cli/gateway_cmd.py
"""marneo gateway — start/stop/status/logs + channel management."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
gateway_app = typer.Typer(help="IM 网关管理。", invoke_without_command=True)
channels_app = typer.Typer(help="渠道管理。")

# Register channels as sub-app of gateway
gateway_app.add_typer(channels_app, name="channels")


# ── Daemon helpers ────────────────────────────────────────────────────────────

def _pid_file() -> Path:
    from marneo.core.paths import get_marneo_dir
    return get_marneo_dir() / "gateway.pid"


def _log_file() -> Path:
    from marneo.core.paths import get_marneo_dir
    return get_marneo_dir() / "gateway.log"


def _read_pid() -> int | None:
    p = _pid_file()
    if not p.exists():
        return None
    try:
        pid = int(p.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, OSError):
        p.unlink(missing_ok=True)
        return None


def _gateway_runner() -> None:
    """Entry point for the background gateway process."""
    import asyncio
    import logging
    logging.basicConfig(
        filename=str(_log_file()),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from marneo.gateway.manager import GatewayManager
    from marneo.gateway.adapters.feishu import FeishuChannelAdapter
    from marneo.gateway.adapters.wechat import WeChatChannelAdapter
    from marneo.gateway.adapters.telegram import TelegramAdapter
    from marneo.gateway.adapters.discord_adapter import DiscordAdapter

    manager = GatewayManager()
    manager.register(FeishuChannelAdapter(manager))
    manager.register(WeChatChannelAdapter(manager))
    manager.register(TelegramAdapter(manager))
    manager.register(DiscordAdapter(manager))

    asyncio.run(manager.run_forever())


# ── Gateway commands ──────────────────────────────────────────────────────────

@gateway_app.callback(invoke_without_command=True)
def gateway_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        cmd_status()


@gateway_app.command("start")
def cmd_start(
    foreground: bool = typer.Option(False, "--fg", help="前台运行（调试用）"),
) -> None:
    """启动 IM 网关（后台守护进程）。"""
    if _read_pid():
        console.print("[yellow]网关已在运行。用 marneo gateway status 查看。[/yellow]")
        raise typer.Exit()

    if foreground:
        console.print(Panel(
            "[bold #FF6611]IM 网关（前台模式）[/bold #FF6611]\n[dim]Ctrl+C 停止[/dim]",
            border_style="#FF6611", padding=(0, 2),
        ))
        _gateway_runner()
        return

    log_path = _log_file()
    pid_path = _pid_file()

    proc = subprocess.Popen(
        [sys.executable, "-c",
         "from marneo.cli.gateway_cmd import _gateway_runner; _gateway_runner()"],
        stdout=open(log_path, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=str(Path.home()),
    )
    pid_path.write_text(str(proc.pid))
    console.print(f"[green]✓ 网关已启动 (PID: {proc.pid})[/green]")
    console.print(f"[dim]日志: {log_path}[/dim]")


@gateway_app.command("stop")
def cmd_stop() -> None:
    """停止 IM 网关。"""
    pid = _read_pid()
    if not pid:
        console.print("[dim]网关未运行。[/dim]")
        raise typer.Exit()
    try:
        os.kill(pid, signal.SIGTERM)
        _pid_file().unlink(missing_ok=True)
        console.print(f"[green]✓ 网关已停止 (PID: {pid})[/green]")
    except OSError as e:
        console.print(f"[red]停止失败: {e}[/red]")
        _pid_file().unlink(missing_ok=True)


@gateway_app.command("status")
def cmd_status() -> None:
    """查看网关状态。"""
    pid = _read_pid()
    if pid:
        console.print(f"[green]🟢 网关运行中 (PID: {pid})[/green]")
        log = _log_file()
        if log.exists():
            lines = log.read_text(encoding="utf-8", errors="ignore").splitlines()
            if lines:
                console.print(f"[dim]最新: {lines[-1][:80]}[/dim]")
    else:
        console.print("[dim]⚪ 网关未运行。运行 marneo gateway start 启动。[/dim]")


@gateway_app.command("logs")
def cmd_logs(n: int = typer.Option(50, "-n")) -> None:
    """查看网关日志。"""
    log = _log_file()
    if not log.exists():
        console.print("[dim]暂无日志。[/dim]")
        return
    lines = log.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
    for line in lines:
        console.print(f"[dim]{line}[/dim]")


# ── Channels sub-commands ─────────────────────────────────────────────────────

KNOWN_PLATFORMS = ["feishu", "wechat", "telegram", "discord"]
PLATFORM_INFO = {
    "feishu":   {"label": "飞书 / Feishu",          "keys": ["app_id", "app_secret"]},
    "wechat":   {"label": "微信 / WeChat (iLink)",   "keys": ["account_id", "token"]},
    "telegram": {"label": "Telegram",               "keys": ["bot_token"]},
    "discord":  {"label": "Discord",                "keys": ["bot_token"]},
}


@channels_app.callback(invoke_without_command=True)
def channels_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        channels_list()


@channels_app.command("list")
def channels_list() -> None:
    """列出所有渠道状态。"""
    from marneo.gateway.config import load_channel_configs

    configs = load_channel_configs()
    t = Table(title="IM 渠道", show_header=True, header_style="bold #FFD700")
    t.add_column("平台")
    t.add_column("名称")
    t.add_column("启用", justify="center")
    t.add_column("已配置", justify="center")

    for platform in KNOWN_PLATFORMS:
        info = PLATFORM_INFO[platform]
        config = configs.get(platform, {})
        enabled = "[green]✓[/green]" if config.get("enabled") else "[dim]○[/dim]"
        has_creds = "[green]✓[/green]" if all(config.get(k) for k in info["keys"]) else "[red]✗[/red]"
        t.add_row(platform, info["label"], enabled, has_creds)

    console.print()
    console.print(t)


@channels_app.command("add")
def channels_add(
    platform: str = typer.Argument(..., help="平台 (feishu/wechat/telegram/discord)"),
) -> None:
    """配置渠道（向导）。"""
    from prompt_toolkit import prompt as pt_prompt
    from marneo.gateway.config import save_channel_config

    if platform not in KNOWN_PLATFORMS:
        console.print(f"[red]未知平台: {platform}[/red]")
        raise typer.Exit(1)

    info = PLATFORM_INFO[platform]
    console.print()
    console.print(Panel(f"[bold #FF6611]配置 {info['label']}[/bold #FF6611]",
                        border_style="#FF6611", padding=(0, 2)))

    config: dict = {"enabled": True}
    for key in info["keys"]:
        try:
            is_secret = "token" in key or "secret" in key
            val = pt_prompt(f"  {key}: ", is_password=is_secret).strip()
            if not val:
                console.print(f"[yellow]{key} 不能为空。[/yellow]")
                raise typer.Exit(1)
            config[key] = val
        except KeyboardInterrupt:
            console.print("\n[dim]已取消。[/dim]")
            raise typer.Exit()

    save_channel_config(platform, config)
    console.print(f"[green]✓ {platform} 配置已保存[/green]")
    console.print(f"[dim]运行 marneo gateway channels test {platform} 验证[/dim]")


@channels_app.command("test")
def channels_test(platform: str = typer.Argument(...)) -> None:
    """测试渠道连接。"""
    from marneo.gateway.config import get_channel_config
    import asyncio as _asyncio

    config = get_channel_config(platform)
    if not config:
        console.print(f"[red]平台 '{platform}' 未配置。[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]测试 {platform}...[/dim]")

    async def _test() -> bool:
        if platform == "feishu":
            from marneo.gateway.adapters.feishu import FeishuChannelAdapter
            from marneo.gateway.manager import GatewayManager
            info = await FeishuChannelAdapter(GatewayManager()).probe_bot(
                config.get("app_id", ""), config.get("app_secret", ""),
                config.get("domain", "feishu"),
            )
            return info is not None
        elif platform == "wechat":
            import httpx
            from marneo.gateway.adapters.wechat import ILINK_BASE_URL, _ilink_get_headers
            base = config.get("base_url", ILINK_BASE_URL)
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        f"{base.rstrip('/')}/ilink/bot/getconfig",
                        headers=_ilink_get_headers(),
                    )
                    return r.status_code in (200, 400)
            except Exception:
                return False
        return False

    ok = _asyncio.run(_test())
    if ok:
        console.print(f"[green]✓ {platform} 连接成功[/green]")
    else:
        console.print(f"[yellow]⚠ {platform} 连接失败[/yellow]")


@channels_app.command("enable")
def channels_enable(platform: str = typer.Argument(...)) -> None:
    """启用渠道。"""
    from marneo.gateway.config import get_channel_config, save_channel_config
    config = get_channel_config(platform) or {}
    config["enabled"] = True
    save_channel_config(platform, config)
    console.print(f"[green]✓ {platform} 已启用[/green]")


@channels_app.command("disable")
def channels_disable(platform: str = typer.Argument(...)) -> None:
    """禁用渠道。"""
    from marneo.gateway.config import get_channel_config, save_channel_config
    config = get_channel_config(platform) or {}
    config["enabled"] = False
    save_channel_config(platform, config)
    console.print(f"[dim]{platform} 已禁用[/dim]")
