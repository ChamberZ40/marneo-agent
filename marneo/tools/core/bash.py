# marneo/tools/core/bash.py
"""Bash execution tool with basic safety checks."""
from __future__ import annotations

import re
import subprocess
from typing import Any

from marneo.tools.registry import registry, tool_result, tool_error

_DEFAULT_TIMEOUT = 60
_MAX_OUTPUT = 50_000

_BLOCKED_PATTERNS = [
    re.compile(r"rm\s+-[rf]{1,2}\s+/(?:\s|$)"),
    re.compile(r":\(\)\s*\{"),
    re.compile(r"mkfs\.[a-z0-9]+\s+/dev/"),
    re.compile(r"dd\s+.*of=/dev/[sh]d"),
    re.compile(r">\s*/dev/[sh]d[a-z]"),
    re.compile(r"\bshutdown\b|\bpoweroff\b|\breboot\b|\bhalt\b"),
    re.compile(r"chmod\s+-[rR]\s+777\s+/"),
]


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
            executable="/bin/bash",
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
    except Exception as exc:
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
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 60)", "default": 60},
            },
            "required": ["command"],
        },
    },
    handler=bash,
    emoji="💻",
)
