# marneo/cli/gateway_cmd.py
"""marneo gateway — start/stop/status/logs + channel management."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

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
    from marneo.gateway.status import get_pid_path
    return get_pid_path()


def _log_file() -> Path:
    from marneo.gateway.status import get_gateway_log_path
    return get_gateway_log_path()


def _read_pid() -> int | None:
    from marneo.gateway.status import read_pid_file
    return read_pid_file()


def _spawn_gateway_process() -> subprocess.Popen[Any]:
    """Spawn the gateway child process; the child writes PID after acquiring the lock."""
    log_path = _log_file()
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from marneo.cli.gateway_cmd import _gateway_runner; _gateway_runner()",
        ],
        stdout=open(log_path, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=str(Path.home()),
    )


def _wait_for_gateway_start(proc: subprocess.Popen[Any], timeout: float = 8.0) -> bool:
    """Return True once the child owns the PID file, is alive, and reports ready."""
    from marneo.gateway.status import read_runtime_status

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        pid = _read_pid()
        state = read_runtime_status() or {}
        if pid == proc.pid and state.get("pid") == proc.pid and state.get("gateway_state") == "running":
            return True
        if state.get("pid") == proc.pid and state.get("gateway_state") == "failed":
            return False
        time.sleep(0.05)
    state = read_runtime_status() or {}
    return (
        _read_pid() == proc.pid
        and proc.poll() is None
        and state.get("pid") == proc.pid
        and state.get("gateway_state") == "running"
    )


def _wait_for_pid_exit(pid: int, timeout: float = 10.0) -> bool:
    """Wait until a PID exits; do not report stop/restart success before this."""
    from marneo.gateway.status import is_process_alive

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_process_alive(pid):
            return True
        time.sleep(0.1)
    return not is_process_alive(pid)


def _remove_pid_file_force() -> None:
    _pid_file().unlink(missing_ok=True)


def _start_background_gateway(action_label: str = "启动") -> subprocess.Popen[Any]:
    proc = _spawn_gateway_process()
    if not _wait_for_gateway_start(proc):
        console.print(f"[red]网关{action_label}失败：子进程未写入 PID 或已退出。请查看日志: {_log_file()}[/red]")
        raise typer.Exit(1)
    return proc


def _terminate_gateway_pid(pid: int, *, restart_requested: bool = False, timeout: float = 10.0) -> bool:
    from marneo.gateway.status import write_runtime_status

    write_runtime_status(
        gateway_state="stopping",
        exit_reason="planned_restart" if restart_requested else "normal_stop",
        restart_requested=restart_requested,
        pid=pid,
    )
    os.kill(pid, signal.SIGTERM)
    if not _wait_for_pid_exit(pid, timeout=timeout):
        return False
    _remove_pid_file_force()
    return True


def _gateway_runner() -> None:
    """Entry point for the foreground/background gateway process."""
    import asyncio
    import logging

    from marneo.gateway.locks import LockUnavailable, acquire_gateway_lock, release_lock
    from marneo.gateway.status import (
        redact_secret_text,
        remove_pid_file,
        write_pid_file,
        write_runtime_status,
    )

    log_path = _log_file()
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger(__name__)

    lock = None
    try:
        lock = acquire_gateway_lock()
    except LockUnavailable as exc:
        message = redact_secret_text(str(exc))
        write_runtime_status(gateway_state="failed", exit_reason="lock_unavailable", error_message=message)
        log.error("Gateway lock unavailable: %s", message)
        raise SystemExit(1) from exc

    try:
        write_pid_file()
        write_runtime_status(gateway_state="starting", active_agents=0, restart_requested=False, exit_reason=None)

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

        # Load all tools (triggers self-registration in registry)
        from marneo.tools.loader import load_all_tools
        load_all_tools()

        async def _run_with_signals() -> None:
            loop = asyncio.get_running_loop()
            stop_event = asyncio.Event()

            def _request_stop() -> None:
                manager.request_stop()
                stop_event.set()

            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(sig, _request_stop)
                except (NotImplementedError, RuntimeError):
                    signal.signal(sig, lambda *_args: _request_stop())

            task = asyncio.create_task(manager.run_forever())
            stop_task = asyncio.create_task(stop_event.wait())
            done, pending = await asyncio.wait(
                {task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task in done:
                manager.request_stop()
                await task
            else:
                stop_task.cancel()
                await task
            for pending_task in pending:
                pending_task.cancel()

        asyncio.run(_run_with_signals())
        write_runtime_status(gateway_state="stopped", exit_reason="normal_stop")
    except KeyboardInterrupt:
        write_runtime_status(gateway_state="stopped", exit_reason="keyboard_interrupt")
        raise
    except BaseException as exc:
        write_runtime_status(
            gateway_state="failed",
            exit_reason=type(exc).__name__,
            error_message=redact_secret_text(str(exc)),
        )
        raise
    finally:
        remove_pid_file()
        release_lock(lock)


# ── Gateway commands ──────────────────────────────────────────────────────────

@gateway_app.callback(invoke_without_command=True)
def gateway_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        cmd_status()


@gateway_app.command("run")
def cmd_run() -> None:
    """前台运行 IM 网关（供 systemd/launchd 或调试使用）。"""
    if _read_pid():
        console.print("[yellow]网关已在运行。用 marneo gateway status 查看。[/yellow]")
        raise typer.Exit()
    console.print(Panel(
        "[bold #FF6611]IM 网关（前台模式）[/bold #FF6611]\n[dim]Ctrl+C 停止[/dim]",
        border_style="#FF6611", padding=(0, 2),
    ))
    _gateway_runner()


@gateway_app.command("start")
def cmd_start(
    foreground: bool = typer.Option(False, "--fg", help="前台运行（兼容旧用法；推荐 marneo gateway run）"),
) -> None:
    """启动 IM 网关；已安装服务时优先交给 systemd/launchd。"""
    if _read_pid():
        console.print("[yellow]网关已在运行。用 marneo gateway status 查看。[/yellow]")
        raise typer.Exit()

    if foreground:
        console.print("[yellow]提示：start --fg 是兼容旧用法，推荐使用 marneo gateway run。[/yellow]")
        cmd_run()
        return

    from marneo.gateway import supervisor

    if supervisor.is_service_installed():
        supervisor.start_service()
        console.print("[green]✓ 已通过系统服务启动网关[/green]")
        console.print("[dim]查看状态: marneo gateway status[/dim]")
        return

    log_path = _log_file()
    console.print("[yellow]未安装系统服务，使用临时后台进程启动。推荐运行 marneo gateway install。[/yellow]")
    proc = _start_background_gateway("启动")
    console.print(f"[green]✓ 网关已启动 (PID: {proc.pid})[/green]")
    console.print(f"[dim]日志: {log_path}[/dim]")


@gateway_app.command("stop")
def cmd_stop() -> None:
    """停止 IM 网关。"""
    from marneo.gateway import supervisor

    if supervisor.is_service_installed():
        supervisor.stop_service()
        console.print("[green]✓ 已通过系统服务停止网关[/green]")
        return

    pid = _read_pid()
    if not pid:
        console.print("[dim]网关未运行。[/dim]")
        raise typer.Exit()
    try:
        if not _terminate_gateway_pid(pid, restart_requested=False):
            console.print(f"[red]停止超时：进程仍在运行 (PID: {pid})[/red]")
            raise typer.Exit(1)
        console.print(f"[green]✓ 网关已停止 (PID: {pid})[/green]")
    except OSError as e:
        console.print(f"[red]停止失败: {e}[/red]")
        _remove_pid_file_force()
        raise typer.Exit(1) from e


@gateway_app.command("restart")
def cmd_restart() -> None:
    """重启 IM 网关。"""
    from marneo.gateway import supervisor

    if supervisor.is_service_installed():
        supervisor.restart_service()
        console.print("[green]✓ 已通过系统服务重启网关[/green]")
        return

    pid = _read_pid()
    if pid:
        try:
            if not _terminate_gateway_pid(pid, restart_requested=True):
                console.print(f"[red]旧进程未退出，已取消重启 (PID: {pid})[/red]")
                raise typer.Exit(1)
            console.print(f"[dim]已停止旧进程 (PID: {pid})[/dim]")
        except OSError as e:
            console.print(f"[red]停止旧进程失败: {e}[/red]")
            _remove_pid_file_force()
            raise typer.Exit(1) from e
    else:
        console.print("[dim]网关未运行，直接启动...[/dim]")

    log_path = _log_file()
    proc = _start_background_gateway("重启")
    console.print(f"[green]✓ 网关已重启 (PID: {proc.pid})[/green]")
    console.print(f"[dim]日志: {log_path}[/dim]")


def _format_state_line(state: dict[str, Any]) -> str:
    gateway_state = state.get("gateway_state") or "unknown"
    channels = state.get("channels") if isinstance(state.get("channels"), dict) else {}
    connected = [
        channel_id for channel_id, detail in channels.items()
        if isinstance(detail, dict) and detail.get("connected", detail.get("state") == "connected")
    ]
    if connected:
        return f"状态: {gateway_state}; channels: {', '.join(sorted(connected))}"
    return f"状态: {gateway_state}; channels: —"


def _format_service_status_line(service: dict[str, object]) -> str | None:
    """Return a compact service-manager status line for `gateway status`."""
    if not service.get("installed"):
        return None
    active = "active" if service.get("active") else "inactive"
    kind = service.get("kind") or "unknown"
    path = service.get("path") or "—"
    returncode = service.get("returncode")
    rc = f"; rc={returncode}" if returncode is not None else ""
    return f"系统服务: {kind}; {active}; path: {path}{rc}"


@gateway_app.command("status")
def cmd_status() -> None:
    """查看网关状态。"""
    from marneo.gateway import supervisor
    from marneo.gateway.status import read_runtime_status, redact_secret_text

    pid = _read_pid()
    state = read_runtime_status()
    service_line: str | None = None
    try:
        service_line = _format_service_status_line(supervisor.service_status())
    except RuntimeError as exc:
        service_line = f"系统服务: 状态查询失败: {exc}"
    if pid:
        console.print(f"[green]🟢 网关运行中 (PID: {pid})[/green]")
        if state:
            console.print(f"[dim]{redact_secret_text(_format_state_line(state))}[/dim]")
        if service_line:
            console.print(f"[dim]{redact_secret_text(service_line)}[/dim]")
        log = _log_file()
        if log.exists():
            lines = log.read_text(encoding="utf-8", errors="ignore").splitlines()
            if lines:
                console.print(f"[dim]最新: {redact_secret_text(lines[-1])[:120]}[/dim]")
    else:
        if state and state.get("gateway_state"):
            console.print(f"[dim]⚪ 网关未运行。最近状态: {state.get('gateway_state')}[/dim]")
        else:
            console.print("[dim]⚪ 网关未运行。运行 marneo gateway start 启动。[/dim]")
        if service_line:
            console.print(f"[dim]{redact_secret_text(service_line)}[/dim]")


@gateway_app.command("logs")
def cmd_logs(n: int = typer.Option(50, "-n")) -> None:
    """查看网关日志。"""
    log = _log_file()
    if not log.exists():
        legacy_log = _pid_file().with_name("gateway.log")
        log = legacy_log if legacy_log.exists() else log
    if not log.exists():
        console.print("[dim]暂无日志。[/dim]")
        return
    from marneo.gateway.status import redact_secret_text
    lines = log.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
    for line in lines:
        console.print(f"[dim]{redact_secret_text(line)}[/dim]")


# ── Channels sub-commands ─────────────────────────────────────────────────────

KNOWN_PLATFORMS = ["feishu", "wechat", "telegram", "discord"]
PLATFORM_INFO = {
    "feishu":   {"label": "飞书 / Feishu",          "keys": ["app_id", "app_secret"]},
    "wechat":   {"label": "微信 / WeChat (iLink)",   "keys": ["account_id", "token"]},
    "telegram": {"label": "Telegram",               "keys": ["bot_token"]},
    "discord":  {"label": "Discord",                "keys": ["bot_token"]},
}


def _install_gateway_service() -> None:
    """Install the preferred system service through the supervisor abstraction."""
    from marneo.gateway import supervisor

    try:
        dst = supervisor.install_service()
    except RuntimeError as exc:
        console.print(f"[red]安装系统服务失败: {exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(f"[green]✓ 已安装系统服务: {dst}[/green]")
    if supervisor.detect_supervisor() == supervisor.SupervisorKind.SYSTEMD_USER:
        console.print("[dim]启用: systemctl --user enable marneo-gateway[/dim]")
        console.print("[dim]启动: systemctl --user start marneo-gateway[/dim]")
    elif supervisor.detect_supervisor() == supervisor.SupervisorKind.LAUNCHD_USER:
        console.print(f"[dim]启用: launchctl load {dst}[/dim]")


@gateway_app.command("install")
def cmd_install() -> None:
    """安装系统服务（推荐命令）。"""
    _install_gateway_service()


@gateway_app.command("install-service")
def cmd_install_service() -> None:
    """安装系统服务（兼容旧命令；推荐 marneo gateway install）。"""
    _install_gateway_service()


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
