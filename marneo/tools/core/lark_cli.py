# marneo/tools/core/lark_cli.py
"""Feishu lark-cli tool — wraps the official lark-cli with marneo credentials."""
from __future__ import annotations

import shlex
import shutil
import subprocess
from typing import Any

from marneo.tools.registry import registry, tool_result, tool_error

_DEFAULT_TIMEOUT = 60
_MAX_OUTPUT = 50_000


def _get_feishu_credentials() -> tuple[str, str, str]:
    """Return (app_id, app_secret, domain) from any configured employee Feishu config."""
    try:
        from marneo.employee.feishu_config import list_configured_employees, load_feishu_config
        for emp in list_configured_employees():
            cfg = load_feishu_config(emp)
            if cfg and cfg.is_complete:
                return cfg.app_id, cfg.app_secret, cfg.domain
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("[lark_cli] credential loading failed: %s", exc)
    return "", "", "feishu"


def _ensure_lark_cli_configured(app_id: str, app_secret: str, brand: str) -> str | None:
    """Run `lark-cli config init` with credentials if not already configured.

    Returns error string on failure, None on success.
    """
    try:
        # Check current config
        check = subprocess.run(
            ["lark-cli", "config", "show"],
            capture_output=True, text=True, timeout=10,
        )
        if app_id and app_id in (check.stdout + check.stderr):
            return None  # Already configured with this app_id

        # Configure with app_id + app_secret via stdin
        proc = subprocess.run(
            ["lark-cli", "config", "init",
             "--app-id", app_id,
             "--app-secret-stdin",
             "--brand", brand],
            input=app_secret,
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return f"lark-cli config init failed: {proc.stderr.strip()[:200]}"
        return None
    except Exception as exc:
        return str(exc)


def lark_cli(args: dict[str, Any], **kw: Any) -> str:
    """Execute a lark-cli command using marneo's Feishu credentials."""
    command = args.get("command", "").strip()
    timeout = int(args.get("timeout", _DEFAULT_TIMEOUT))

    if not command:
        return tool_error("command is required")

    # Check lark-cli is available
    lark_bin = shutil.which("lark-cli")
    if not lark_bin:
        return tool_error("lark-cli is not installed. Run: npm install -g @larksuite/cli")

    # Get credentials from marneo config
    app_id, app_secret, domain = _get_feishu_credentials()
    if not app_id or not app_secret:
        return tool_error(
            "No Feishu credentials configured. Run: marneo employees feishu setup <name>"
        )

    # Ensure lark-cli is configured with current credentials
    brand = "lark" if domain == "lark" else "feishu"
    err = _ensure_lark_cli_configured(app_id, app_secret, brand)
    if err:
        return tool_error(f"lark-cli configuration failed: {err}")

    # Build command — always run as bot using marneo's app credentials
    try:
        cmd_parts = shlex.split(command)
    except ValueError as exc:
        return tool_error(f"Invalid command syntax: {exc}")

    # Append --as bot and --format json if not already present
    if "--as" not in cmd_parts:
        cmd_parts += ["--as", "bot"]
    if "--format" not in cmd_parts and not any(c.startswith("+") for c in cmd_parts[:2]):
        cmd_parts += ["--format", "json"]

    full_cmd = [lark_bin] + cmd_parts

    try:
        proc = subprocess.run(
            full_cmd,
            capture_output=True, text=True,
            timeout=timeout,
        )
        stdout = proc.stdout[:_MAX_OUTPUT]
        stderr = proc.stderr[:_MAX_OUTPUT]
        if len(proc.stdout) > _MAX_OUTPUT:
            stdout += "\n... (truncated)"

        return tool_result(
            stdout=stdout,
            stderr=stderr if stderr else None,
            exit_code=proc.returncode,
            command=" ".join(full_cmd[1:]),  # exclude binary path
        )
    except subprocess.TimeoutExpired:
        return tool_error(f"lark-cli timed out after {timeout}s")
    except Exception as exc:
        return tool_error(str(exc))


# ── Register ──────────────────────────────────────────────────────────────────

registry.register(
    name="lark_cli",
    description="Execute Feishu/Lark CLI commands. Uses marneo's configured app credentials automatically.",
    schema={
        "name": "lark_cli",
        "description": (
            "Execute any lark-cli command to interact with Feishu/Lark. "
            "Key commands: "
            "'chat members --chat-id oc_xxx' (list group members with open_id to find who to @mention), "
            "'calendar +agenda', "
            "'docs +create --content \"...\"', "
            "'im +messages-send --chat-id oc_xxx --text hello'. "
            "Run as bot identity automatically. Use 'schema <command>' to explore parameters."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "lark-cli command (without 'lark-cli' prefix). E.g. 'calendar +agenda' or 'docs +create --content \"# Title\"'",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 60)",
                    "default": 60,
                },
            },
            "required": ["command"],
        },
    },
    handler=lark_cli,
    emoji="🪶",
    check_fn=lambda: bool(shutil.which("lark-cli")),
)
