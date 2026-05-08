"""Gateway service supervisor helpers.

This module keeps service-manager specific behavior out of the CLI.  It renders
user-service safe systemd/launchd units dynamically so installed packages do not
rely on repository-relative deploy templates.
"""
from __future__ import annotations

from enum import Enum
import html
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any

from marneo.gateway.status import get_logs_dir

SERVICE_NAME = "marneo-gateway"
SYSTEMD_UNIT = "marneo-gateway.service"
LAUNCHD_LABEL = "com.marneo.gateway"
LAUNCHD_PLIST = f"{LAUNCHD_LABEL}.plist"


class SupervisorKind(str, Enum):
    """Supported gateway supervision backends."""

    SYSTEMD_USER = "systemd_user"
    LAUNCHD_USER = "launchd_user"
    POPEN_FALLBACK = "popen_fallback"


def detect_supervisor() -> SupervisorKind:
    """Detect the preferred user-level service supervisor for this platform."""
    if sys.platform == "darwin":
        return SupervisorKind.LAUNCHD_USER
    if sys.platform.startswith("linux"):
        return SupervisorKind.SYSTEMD_USER
    return SupervisorKind.POPEN_FALLBACK


def resolve_marneo_argv() -> list[str]:
    """Return argv for the installed marneo command used in generated units."""
    found = shutil.which("marneo")
    if found:
        return [found]
    argv0 = Path(sys.argv[0]).expanduser()
    if argv0.name == "marneo" and (argv0.is_absolute() or shutil.which(str(argv0))):
        return [str(argv0)]
    return [sys.executable, "-m", "marneo.cli.app"]


def resolve_marneo_command() -> str:
    """Return a shell-safe display/render string for the marneo command."""
    return shlex.join(resolve_marneo_argv())


def _argv_from_command(marneo_cmd: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(marneo_cmd, str):
        return shlex.split(marneo_cmd)
    return [str(part) for part in marneo_cmd]


def _systemd_unit_path(home: Path) -> Path:
    return home / ".config/systemd/user" / SYSTEMD_UNIT


def _launchd_plist_path(home: Path) -> Path:
    return home / "Library/LaunchAgents" / LAUNCHD_PLIST


def service_path(kind: SupervisorKind | None = None, home: Path | None = None) -> Path | None:
    """Return the target service file path for the current or supplied supervisor."""
    kind = kind or detect_supervisor()
    home = home or Path.home()
    if kind == SupervisorKind.SYSTEMD_USER:
        return _systemd_unit_path(home)
    if kind == SupervisorKind.LAUNCHD_USER:
        return _launchd_plist_path(home)
    return None


def is_service_installed(kind: SupervisorKind | None = None, home: Path | None = None) -> bool:
    """Return True when a user service file has been installed."""
    path = service_path(kind, home)
    return bool(path and path.exists())


def render_systemd_service(marneo_cmd: str | list[str] | tuple[str, ...], home: Path) -> str:
    """Render a systemd user service with dynamic executable and safe paths."""
    _ = home  # systemd user units should use %h so files remain portable.
    command = shlex.join([*_argv_from_command(marneo_cmd), "gateway", "run"])
    return f"""[Unit]
Description=Marneo Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={command}
Restart=on-failure
RestartSec=5
WorkingDirectory=%h
Environment=HOME=%h
StandardOutput=append:%h/.marneo/logs/gateway.log
StandardError=append:%h/.marneo/logs/gateway.log
SyslogIdentifier=marneo-gateway

[Install]
WantedBy=default.target
"""


def render_launchd_plist(marneo_cmd: str | list[str] | tuple[str, ...], home: Path) -> str:
    """Render a macOS LaunchAgent plist with dynamic executable and log path."""
    argv = [*_argv_from_command(marneo_cmd), "gateway", "run"]
    args = "\n".join(f"        <string>{html.escape(part)}</string>" for part in argv)
    escaped_home = html.escape(str(home))
    escaped_log = html.escape(str(home / ".marneo/logs/gateway.log"))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>{escaped_home}</string>
    <key>StandardOutPath</key>
    <string>{escaped_log}</string>
    <key>StandardErrorPath</key>
    <string>{escaped_log}</string>
</dict>
</plist>
"""


def install_service() -> Path:
    """Render and install the current platform's user service file."""
    kind = detect_supervisor()
    if kind == SupervisorKind.POPEN_FALLBACK:
        raise RuntimeError(f"unsupported supervisor platform: {sys.platform}")

    home = Path.home()
    get_logs_dir()
    marneo_argv = resolve_marneo_argv()
    target = service_path(kind, home)
    if target is None:  # pragma: no cover - guarded by kind check above.
        raise RuntimeError(f"unsupported supervisor kind: {kind}")
    target.parent.mkdir(parents=True, exist_ok=True)

    if kind == SupervisorKind.SYSTEMD_USER:
        content = render_systemd_service(marneo_argv, home)
    else:
        content = render_launchd_plist(marneo_argv, home)
    target.write_text(content, encoding="utf-8")
    return target


def _run_command(cmd: list[str], *, capture_output: bool = False, check: bool = True) -> Any:
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"service manager command not found: {cmd[0]}") from exc
    if check and result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        suffix = f": {details}" if details else ""
        raise RuntimeError(f"service command failed ({' '.join(cmd)}){suffix}")
    if capture_output:
        return result
    return result


def _require_installed(kind: SupervisorKind) -> None:
    if not is_service_installed(kind):
        raise RuntimeError("gateway service is not installed; run `marneo gateway install` first")


def start_service() -> None:
    """Start the installed user service without invoking the gateway runner directly."""
    kind = detect_supervisor()
    _require_installed(kind)
    if kind == SupervisorKind.SYSTEMD_USER:
        _run_command(["systemctl", "--user", "start", SERVICE_NAME])
    elif kind == SupervisorKind.LAUNCHD_USER:
        _run_command(["launchctl", "load", str(service_path(kind))])
    else:
        raise RuntimeError("no service supervisor available")


def stop_service() -> None:
    """Stop the installed user service."""
    kind = detect_supervisor()
    _require_installed(kind)
    if kind == SupervisorKind.SYSTEMD_USER:
        _run_command(["systemctl", "--user", "stop", SERVICE_NAME])
    elif kind == SupervisorKind.LAUNCHD_USER:
        _run_command(["launchctl", "unload", str(service_path(kind))])
    else:
        raise RuntimeError("no service supervisor available")


def restart_service() -> None:
    """Restart the installed user service."""
    kind = detect_supervisor()
    _require_installed(kind)
    if kind == SupervisorKind.SYSTEMD_USER:
        _run_command(["systemctl", "--user", "restart", SERVICE_NAME])
    elif kind == SupervisorKind.LAUNCHD_USER:
        stop_service()
        start_service()
    else:
        raise RuntimeError("no service supervisor available")


def service_status() -> dict[str, object]:
    """Return best-effort status for the configured service supervisor."""
    kind = detect_supervisor()
    path = service_path(kind)
    payload: dict[str, object] = {
        "kind": kind.value,
        "installed": bool(path and path.exists()),
        "path": str(path) if path else None,
    }
    if kind == SupervisorKind.SYSTEMD_USER and payload["installed"]:
        result = _run_command(["systemctl", "--user", "is-active", SYSTEMD_UNIT], capture_output=True, check=False)
        payload["active"] = getattr(result, "stdout", "").strip() == "active"
        payload["returncode"] = getattr(result, "returncode", None)
    elif kind == SupervisorKind.LAUNCHD_USER and payload["installed"]:
        result = _run_command(["launchctl", "list", LAUNCHD_LABEL], capture_output=True, check=False)
        payload["active"] = getattr(result, "returncode", 1) == 0
        payload["returncode"] = getattr(result, "returncode", None)
    else:
        payload["active"] = False
    return payload
