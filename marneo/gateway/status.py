"""Gateway runtime status helpers.

This module is intentionally platform-neutral and side-effect-light so CLI,
health checks, supervisors, and tests can share the same gateway ground truth.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marneo.core.paths import get_marneo_dir

GATEWAY_KIND = "marneo-gateway"
RUNTIME_STATUS_FILE = "gateway_state.json"
PID_FILE = "gateway.pid"

_UNSET = object()


def utc_now_iso() -> str:
    """Return a compact UTC ISO timestamp with a trailing Z."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_pid_path() -> Path:
    """Return the gateway PID file path."""
    return get_marneo_dir() / PID_FILE


def get_runtime_status_path() -> Path:
    """Return the structured gateway runtime status path."""
    return get_marneo_dir() / RUNTIME_STATUS_FILE


def get_logs_dir() -> Path:
    """Return the gateway logs directory, creating it if needed."""
    path = get_marneo_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_gateway_log_path() -> Path:
    """Return the canonical gateway log path."""
    return get_logs_dir() / "gateway.log"


def is_process_alive(pid: int) -> bool:
    """Return True when *pid* appears to be alive on this machine."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def write_pid_file(pid: int | None = None) -> None:
    """Write the gateway PID file."""
    path = get_pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid or os.getpid()), encoding="utf-8")


def read_pid_file() -> int | None:
    """Read the gateway PID file and remove it if stale or invalid."""
    path = get_pid_path()
    if not path.exists():
        return None
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return None
    if not is_process_alive(pid):
        path.unlink(missing_ok=True)
        return None
    return pid


def remove_pid_file() -> None:
    """Remove the PID file when it belongs to this process or is stale."""
    path = get_pid_path()
    try:
        if not path.exists():
            return
        raw = path.read_text(encoding="utf-8").strip()
        file_pid = int(raw) if raw else None
        if file_pid is not None and file_pid != os.getpid() and is_process_alive(file_pid):
            return
        path.unlink(missing_ok=True)
    except Exception:
        # PID cleanup must never mask gateway shutdown.
        pass


def _default_runtime_status() -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "kind": GATEWAY_KIND,
        "pid": os.getpid(),
        "start_time": now,
        "updated_at": now,
        "gateway_state": "starting",
        "exit_reason": None,
        "restart_requested": False,
        "active_agents": 0,
        "channels": {},
    }


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def read_runtime_status() -> dict[str, Any] | None:
    """Read the structured runtime status file."""
    return _read_json_file(get_runtime_status_path())


_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|apikey|app[_-]?secret|client[_-]?secret|access[_-]?token|"
    r"refresh[_-]?token|access[_-]?key|ticket|password|passwd|bot[_-]?token|"
    r"authorization|auth[_-]?header)"
)


def _redact_value(value: Any) -> Any:
    """Recursively redact diagnostic payloads before they touch disk."""
    if isinstance(value, str):
        return redact_secret_text(value)
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            redacted[key_text] = "***" if _SENSITIVE_KEY_RE.search(key_text) and item else _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    return value


def write_runtime_status(
    *,
    gateway_state: Any = _UNSET,
    exit_reason: Any = _UNSET,
    restart_requested: Any = _UNSET,
    active_agents: Any = _UNSET,
    channels: Any = _UNSET,
    error_code: Any = _UNSET,
    error_message: Any = _UNSET,
    pid: int | None = None,
) -> None:
    """Merge fields into `gateway_state.json`.

    Corrupt/missing JSON is replaced with a valid default record. All diagnostic
    text is redacted before writing so status/log tooling never persists secrets.
    """
    path = get_runtime_status_path()
    payload = _read_json_file(path) or _default_runtime_status()
    payload.setdefault("kind", GATEWAY_KIND)
    payload.setdefault("start_time", utc_now_iso())
    payload.setdefault("channels", {})
    payload.setdefault("exit_reason", None)
    payload.setdefault("restart_requested", False)
    payload.setdefault("active_agents", 0)

    payload["pid"] = int(pid) if pid is not None else os.getpid()
    payload["updated_at"] = utc_now_iso()

    if gateway_state is not _UNSET:
        payload["gateway_state"] = gateway_state
    if exit_reason is not _UNSET:
        payload["exit_reason"] = _redact_value(exit_reason)
    if restart_requested is not _UNSET:
        payload["restart_requested"] = bool(restart_requested)
    if active_agents is not _UNSET:
        payload["active_agents"] = max(0, int(active_agents))
    if channels is not _UNSET:
        payload["channels"] = _redact_value(channels if isinstance(channels, dict) else {})
    if error_code is not _UNSET:
        payload["error_code"] = _redact_value(error_code)
    if error_message is not _UNSET:
        payload["error_message"] = _redact_value(error_message) if error_message else error_message

    payload["channels"] = _redact_value(payload.get("channels", {}))
    _write_json_atomic(path, payload)


def update_channel_status(channel_id: str, status: dict[str, Any]) -> None:
    """Merge one channel status snapshot into `gateway_state.json`."""
    path = get_runtime_status_path()
    payload = _read_json_file(path) or _default_runtime_status()
    channels = payload.setdefault("channels", {})
    if not isinstance(channels, dict):
        channels = {}
        payload["channels"] = channels

    previous = channels.get(channel_id, {})
    if not isinstance(previous, dict):
        previous = {}
    merged = {**previous, **_redact_value(status)}
    merged["channel_id"] = channel_id
    merged["updated_at"] = utc_now_iso()
    channels[channel_id] = _redact_value(merged)
    payload["pid"] = os.getpid()
    payload["updated_at"] = utc_now_iso()
    payload.setdefault("kind", GATEWAY_KIND)
    payload.setdefault("gateway_state", "running")
    payload.setdefault("active_agents", 0)
    payload.setdefault("restart_requested", False)
    payload.setdefault("exit_reason", None)
    payload["channels"] = _redact_value(channels)

    _write_json_atomic(path, payload)


_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(['\"]?)(api[_-]?key|apikey|app[_-]?secret|client[_-]?secret|access[_-]?token|"
    r"refresh[_-]?token|access[_-]?key|ticket|password|passwd|bot[_-]?token)\1\s*[:=]\s*(['\"]?)([^\s,'\",)}\]]+)\3"
)
_AUTH_BEARER_RE = re.compile(
    r"(?i)(['\"]?authorization['\"]?\s*[:=]\s*['\"]?(?:Bearer\s+)?)([A-Za-z0-9._\-]{12,})"
)
_SK_RE = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{16,}\b")



def redact_secret_text(text: str) -> str:
    """Redact common provider/Feishu credentials from diagnostic text."""
    if not text:
        return text
    redacted = _AUTH_BEARER_RE.sub(r"\1***", text)
    redacted = _SK_RE.sub("sk-***", redacted)

    def _mask_assignment(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}{match.group(1)}=***"

    return _SECRET_ASSIGNMENT_RE.sub(_mask_assignment, redacted)
