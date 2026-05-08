"""Gateway runtime and scoped identity locks."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from marneo.core.paths import get_marneo_dir
from marneo.gateway.status import utc_now_iso

try:  # POSIX-only for now; Marneo's current service targets are macOS/Linux.
    import fcntl
except ImportError:  # pragma: no cover - Windows is not a supported supervisor target yet.
    fcntl = None  # type: ignore[assignment]


class LockUnavailable(RuntimeError):
    """Raised when a gateway/scoped lock is already held."""


@dataclass
class LockHandle:
    """Open file handle that owns an advisory lock."""

    path: Path
    file: TextIO
    metadata: dict[str, Any]


def _locks_root() -> Path:
    path = get_marneo_dir() / "gateway-locks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _hash_identity(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _redact_lock_metadata(metadata: Any) -> Any:
    from marneo.gateway.status import _redact_value

    if isinstance(metadata, dict):
        return _redact_value(metadata)
    return {}


def _acquire(path: Path, payload: dict[str, Any]) -> LockHandle:
    if fcntl is None:
        raise RuntimeError("gateway locks require fcntl on this platform")
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        fh.close()
        raise LockUnavailable(f"gateway lock is already held: {path}") from exc

    payload = {**payload, "pid": os.getpid(), "updated_at": utc_now_iso()}
    payload["metadata"] = _redact_lock_metadata(payload.get("metadata", {}))
    fh.seek(0)
    fh.truncate()
    json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
    fh.write("\n")
    fh.flush()
    os.fsync(fh.fileno())
    return LockHandle(path=path, file=fh, metadata=payload)


def acquire_gateway_lock() -> LockHandle:
    """Acquire the single-instance gateway lock for this Marneo home."""
    return _acquire(
        get_marneo_dir() / "gateway.lock",
        {
            "kind": "marneo-gateway-lock",
            "scope": "gateway",
            "identity_hash": "local-marneo-home",
            "metadata": {},
        },
    )


def acquire_scoped_lock(
    scope: str,
    identity: str,
    metadata: dict[str, Any] | None = None,
) -> LockHandle:
    """Acquire a lock for an external platform identity.

    The raw identity is intentionally never written to disk; only a SHA-256 hash
    is used in the path and payload. Use this for values like Feishu app_id.
    """
    if not scope.strip():
        raise ValueError("scope is required")
    if not identity:
        raise ValueError("identity is required")
    identity_hash = _hash_identity(identity)
    safe_scope = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in scope.strip())
    path = _locks_root() / safe_scope / f"{identity_hash}.lock"
    return _acquire(
        path,
        {
            "kind": "marneo-gateway-lock",
            "scope": safe_scope,
            "identity_hash": identity_hash,
            "metadata": metadata or {},
        },
    )


def release_lock(handle: LockHandle | None) -> None:
    """Release an acquired lock handle."""
    if handle is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle.file.fileno(), fcntl.LOCK_UN)
    finally:
        handle.file.close()
