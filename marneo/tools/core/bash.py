# marneo/tools/core/bash.py
"""Bash execution tool with basic safety checks.

Trust model: this tool is agent-internal. The LLM generates the command string,
which is passed directly to /bin/bash via shell=True. The blocklist is a last-resort
guard against clearly catastrophic commands, not a security boundary against a
fully adversarial caller.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from typing import Any

from marneo.tools.registry import registry, tool_result, tool_error

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 120
_MAX_OUTPUT = 50_000

# Block clearly catastrophic patterns only.
# False-positive risk: prefer narrow patterns that won't hit common log/doc searches.
_BLOCKED_PATTERNS = [
    # rm targeting root or critical system dirs
    re.compile(r"rm\s+-[rRf]{1,3}\s+/(?:$|\s|etc|usr|var|home|bin|sbin|lib|boot|sys|proc)"),
    # fork bomb
    re.compile(r":\(\)\s*\{"),
    # format disk
    re.compile(r"mkfs\.[a-z0-9]+\s+/dev/"),
    # dd overwriting any block device (nvme/vda/mmcblk/sda/hda)
    re.compile(r"dd\s+.*of=/dev/"),
    # redirect to block device
    re.compile(r">\s*/dev/(?:sd|hd|nvme|vd|mmcblk)[a-z0-9]"),
    # shutdown/reboot/halt/poweroff as executing binary (not in strings/args)
    re.compile(r"(?:^|[;|&`(\s])(?:sudo\s+)?(?:shutdown|poweroff|reboot|halt)\b"),
    # chmod 777 on root
    re.compile(r"chmod\s+-[rR]\s+777\s+/"),
]

# Resolve bash path once at import; fail clearly if missing
_BASH = shutil.which("bash") or "/bin/bash"


def _is_blocked(command: str) -> bool:
    for p in _BLOCKED_PATTERNS:
        if p.search(command):
            return True
    return False


def bash(args: dict[str, Any], **kw: Any) -> str:
    command = args.get("command", "").strip()
    timeout = int(args.get("timeout", _DEFAULT_TIMEOUT))

    if not command:
        return tool_error("command is required")
    if _is_blocked(command):
        return tool_error(f"Command blocked for safety: {command[:80]}")

    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            executable=_BASH,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        if len(stdout) > _MAX_OUTPUT:
            stdout = stdout[:_MAX_OUTPUT] + "\n... (stdout truncated)"
        if len(stderr) > _MAX_OUTPUT:
            stderr = stderr[:_MAX_OUTPUT] + "\n... (stderr truncated)"
        return tool_result(stdout=stdout, stderr=stderr, exit_code=proc.returncode)
    except subprocess.TimeoutExpired:
        return tool_error(f"Command timed out after {timeout}s")
    except FileNotFoundError:
        return tool_error(f"bash not found at {_BASH}")
    except Exception as exc:
        log.error("[bash] Unexpected error: %s", exc, exc_info=True)
        return tool_error(str(exc))


registry.register(
    name="bash",
    description="Execute a bash shell command and return stdout, stderr, exit code.",
    schema={
        "name": "bash",
        "description": "Execute a bash command. Returns stdout, stderr, and exit_code.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Bash command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)", "default": 120},
            },
            "required": ["command"],
        },
    },
    handler=bash,
    emoji="💻",
)
