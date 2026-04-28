# marneo/tools/mcp_bridge.py
"""MCP protocol bridge -- connect to any MCP server and register its tools.

Hermes-agent pattern: subprocess + stdin/stdout JSON-RPC communication.
Language-agnostic: works with Node.js, Go, Rust, Python MCP servers.

Architecture:
    A dedicated background event loop (_mcp_loop) runs in a daemon thread.
    Each MCP server connection runs as a long-lived asyncio Task on this
    loop, keeping its transport context alive.  Tool call coroutines are
    scheduled onto the loop via run_coroutine_threadsafe().

    On shutdown, each server Task is signalled to exit its async-with
    block, ensuring cancel-scope cleanup happens in the same Task that
    opened the connection (required by anyio).

Thread safety:
    McpBridge and McpManager guard mutable state with threading locks
    so the code is safe under free-threading (Python 3.13+).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import shutil
import sys
import threading
from typing import Any, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful import -- MCP SDK is an optional dependency
# ---------------------------------------------------------------------------

MCP_AVAILABLE = False
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    MCP_AVAILABLE = True
except ImportError:
    log.debug("mcp package not installed -- MCP bridge disabled")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TOOL_TIMEOUT = 120  # seconds per tool call
_DEFAULT_CONNECT_TIMEOUT = 60  # seconds for initial connection
_MAX_RECONNECT_RETRIES = 3
_MAX_BACKOFF_SECONDS = 30

# Environment variables safe to pass to subprocesses
_SAFE_ENV_KEYS = frozenset({
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR",
})

# Regex for credential patterns to strip from error messages
_CREDENTIAL_PATTERN = re.compile(
    r"(?:"
    r"ghp_[A-Za-z0-9_]{1,255}"
    r"|sk-[A-Za-z0-9_]{1,255}"
    r"|Bearer\s+\S+"
    r"|token=[^\s&,;\"']{1,255}"
    r"|secret=[^\s&,;\"']{1,255}"
    r")",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Background event loop (shared by all MCP bridges)
# ---------------------------------------------------------------------------

_mcp_loop: Optional[asyncio.AbstractEventLoop] = None
_mcp_thread: Optional[threading.Thread] = None
_loop_lock = threading.Lock()


def _ensure_mcp_loop() -> asyncio.AbstractEventLoop:
    """Start the dedicated MCP background event loop (once)."""
    global _mcp_loop, _mcp_thread
    with _loop_lock:
        if _mcp_loop is not None and _mcp_loop.is_running():
            return _mcp_loop

        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        thread = threading.Thread(target=_run, daemon=True, name="mcp-loop")
        thread.start()
        _mcp_loop = loop
        _mcp_thread = thread
        return loop


def _run_on_mcp_loop(coro: Any, timeout: float = 120) -> Any:
    """Schedule a coroutine on the MCP loop and block until it completes."""
    loop = _ensure_mcp_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


# ---------------------------------------------------------------------------
# Security / env helpers
# ---------------------------------------------------------------------------

def _build_safe_env(user_env: Optional[dict]) -> dict:
    """Build a filtered environment for stdio subprocesses.

    Only passes through safe baseline variables plus any explicitly
    specified by the user config.  Prevents leaking API keys etc.
    """
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in _SAFE_ENV_KEYS or key.startswith("XDG_"):
            env[key] = value
    if user_env:
        env.update(user_env)
    return env


def _resolve_env_vars(env: Optional[dict[str, str]]) -> Optional[dict[str, str]]:
    """Expand ${VAR} references in environment variable values."""
    if not env:
        return env
    resolved: dict[str, str] = {}
    for key, value in env.items():
        if not isinstance(value, str):
            resolved[key] = str(value)
            continue
        m = re.fullmatch(r"\$\{?(\w+)\}?", value.strip())
        if m:
            resolved[key] = os.environ.get(m.group(1), value)
        else:
            resolved[key] = value
    return resolved


def _sanitize_error(text: str) -> str:
    """Strip credential-like patterns from error text."""
    return _CREDENTIAL_PATTERN.sub("[REDACTED]", text)


def _sanitize_name(value: str) -> str:
    """Return a name component safe for tool name generation.

    Replaces any character outside [A-Za-z0-9_] with underscore.
    """
    return re.sub(r"[^A-Za-z0-9_]", "_", str(value or ""))


def _resolve_command(command: str, env: dict) -> tuple[str, dict]:
    """Resolve a stdio command against the subprocess environment.

    Ensures bare npx/npm/node commands resolve correctly even
    under a filtered PATH.
    """
    resolved = os.path.expanduser(str(command).strip())
    resolved_env = dict(env or {})

    if os.sep not in resolved:
        path_arg = resolved_env.get("PATH")
        which_hit = shutil.which(resolved, path=path_arg)
        if which_hit:
            resolved = which_hit

    command_dir = os.path.dirname(resolved)
    if command_dir:
        existing_path = resolved_env.get("PATH", "")
        parts = [p for p in existing_path.split(os.pathsep) if p]
        if command_dir not in parts:
            parts = [command_dir, *parts]
        resolved_env["PATH"] = os.pathsep.join(parts) if parts else command_dir

    return resolved, resolved_env


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _normalize_input_schema(schema: Optional[dict]) -> dict:
    """Normalize an MCP tool input schema for LLM tool-calling.

    Handles missing type fields, dangling required entries, and
    draft-07 definitions -> $defs rewrite.
    """
    if not schema:
        return {"type": "object", "properties": {}}

    def _rewrite_refs(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                out_key = "$defs" if k == "definitions" else k
                out[out_key] = _rewrite_refs(v)
            ref = out.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/definitions/"):
                out["$ref"] = "#/$defs/" + ref[len("#/definitions/"):]
            return out
        if isinstance(node, list):
            return [_rewrite_refs(item) for item in node]
        return node

    def _repair(node: Any) -> Any:
        if isinstance(node, list):
            return [_repair(item) for item in node]
        if not isinstance(node, dict):
            return node

        repaired = {k: _repair(v) for k, v in node.items()}

        if not repaired.get("type") and (
            "properties" in repaired or "required" in repaired
        ):
            repaired["type"] = "object"

        if repaired.get("type") == "object":
            if not isinstance(repaired.get("properties"), dict):
                repaired["properties"] = {}
            required = repaired.get("required")
            if isinstance(required, list):
                props = repaired.get("properties") or {}
                valid = [r for r in required if isinstance(r, str) and r in props]
                if valid:
                    repaired["required"] = valid
                else:
                    repaired.pop("required", None)

        return repaired

    normalized = _rewrite_refs(schema)
    normalized = _repair(normalized)

    if not isinstance(normalized, dict):
        return {"type": "object", "properties": {}}
    if normalized.get("type") == "object" and "properties" not in normalized:
        normalized["properties"] = {}
    return normalized


def _convert_mcp_tool_schema(server_name: str, mcp_tool: Any) -> dict:
    """Convert an MCP tool to the marneo registry schema format.

    Returns a dict with name, description, and parameters keys.
    """
    safe_tool = _sanitize_name(mcp_tool.name)
    safe_server = _sanitize_name(server_name)
    prefixed_name = f"mcp_{safe_server}_{safe_tool}"
    return {
        "name": prefixed_name,
        "description": (
            mcp_tool.description
            or f"MCP tool {mcp_tool.name} from server '{server_name}'"
        ),
        "parameters": _normalize_input_schema(
            getattr(mcp_tool, "inputSchema", None)
        ),
    }


# ---------------------------------------------------------------------------
# Stderr redirection for MCP subprocesses
# ---------------------------------------------------------------------------

_stderr_fh: Optional[Any] = None
_stderr_lock = threading.Lock()


def _get_stderr_log() -> Any:
    """Return a shared append-mode file handle for MCP subprocess stderr.

    Redirects MCP server output away from the terminal to prevent
    TUI corruption.  Falls back to /dev/null.
    """
    global _stderr_fh
    with _stderr_lock:
        if _stderr_fh is not None:
            return _stderr_fh
        try:
            from marneo.core.paths import get_marneo_dir
            log_dir = get_marneo_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "mcp-stderr.log"
            fh = open(log_path, "a", encoding="utf-8", errors="replace", buffering=1)
            fh.fileno()  # verify real fd
            _stderr_fh = fh
        except Exception:
            try:
                _stderr_fh = open(os.devnull, "w", encoding="utf-8")
            except Exception:
                _stderr_fh = sys.stderr
        return _stderr_fh


# ---------------------------------------------------------------------------
# McpBridge -- manages a single MCP server connection
# ---------------------------------------------------------------------------

class McpBridge:
    """Manages a connection to one MCP server via stdio transport."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str],
        env: Optional[dict[str, str]] = None,
        timeout: int = _DEFAULT_TOOL_TIMEOUT,
    ) -> None:
        """
        Args:
            name: Prefix for tool names (e.g. "lark" -> tools become "mcp_lark_<tool>").
            command: Executable to spawn (e.g. "npx").
            args: Command arguments (e.g. ["-y", "@larksuite/cli", "mcp", "serve"]).
            env: Environment variables for the subprocess. ${VAR} refs are expanded.
            timeout: Tool call timeout in seconds.
        """
        self.name = name
        self.command = command
        self.args = args
        self.env = _resolve_env_vars(env)
        self.timeout = timeout

        self._session: Optional[Any] = None
        self._tools: list[Any] = []
        self._registered_names: list[str] = []
        self._connected = False
        self._error: Optional[str] = None
        self._task: Optional[Any] = None
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def tool_count(self) -> int:
        with self._lock:
            return len(self._tools)

    @property
    def error(self) -> Optional[str]:
        with self._lock:
            return self._error

    # -- Connection lifecycle -----------------------------------------------

    async def connect(self) -> bool:
        """Start subprocess, establish MCP connection, discover tools.

        Returns True if connection and tool discovery succeeded.
        """
        if not MCP_AVAILABLE:
            self._error = "mcp package not installed"
            log.warning("[MCP:%s] %s", self.name, self._error)
            return False

        loop = _ensure_mcp_loop()
        self._ready.clear()
        self._shutdown.clear()

        # Launch the server task on the MCP background loop
        self._task = asyncio.run_coroutine_threadsafe(
            self._run(), loop
        )

        # Wait for the server to become ready (or fail)
        try:
            await asyncio.wait_for(
                asyncio.wrap_future(
                    asyncio.run_coroutine_threadsafe(self._ready.wait(), loop)
                ),
                timeout=_DEFAULT_CONNECT_TIMEOUT,
            )
        except (asyncio.TimeoutError, Exception) as exc:
            with self._lock:
                self._error = f"Connection timeout: {exc}"
                self._connected = False
            log.error("[MCP:%s] Connection timeout", self.name)
            return False

        return self.is_connected

    async def disconnect(self) -> None:
        """Clean shutdown of subprocess and connection."""
        self._shutdown.set()

        if self._task and not self._task.done():
            try:
                self._task.result(timeout=5)
            except (concurrent.futures.TimeoutError, Exception):
                self._task.cancel()

        with self._lock:
            self._session = None
            self._connected = False
            self._tools = []

        log.info("[MCP:%s] Disconnected", self.name)

    async def _run(self) -> None:
        """Long-lived coroutine: connect, discover, wait for shutdown.

        Includes automatic reconnection with exponential backoff.
        """
        retries = 0
        backoff = 1.0

        while not self._shutdown.is_set():
            try:
                await self._run_stdio()
                break
            except Exception as exc:
                with self._lock:
                    self._session = None
                    self._connected = False

                if self._shutdown.is_set():
                    break

                retries += 1
                if retries > _MAX_RECONNECT_RETRIES:
                    error_msg = _sanitize_error(str(exc))
                    with self._lock:
                        self._error = (
                            f"Failed after {retries} attempts: {error_msg}"
                        )
                    log.error(
                        "[MCP:%s] Connection failed after %d retries: %s",
                        self.name, _MAX_RECONNECT_RETRIES, error_msg,
                    )
                    self._ready.set()
                    return

                log.warning(
                    "[MCP:%s] Connection lost (attempt %d/%d), "
                    "retrying in %.0fs: %s",
                    self.name, retries, _MAX_RECONNECT_RETRIES,
                    backoff, exc,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)

    async def _run_stdio(self) -> None:
        """Establish stdio transport, initialize session, discover tools."""
        safe_env = _build_safe_env(self.env)
        command, safe_env = _resolve_command(self.command, safe_env)

        server_params = StdioServerParameters(
            command=command,
            args=self.args,
            env=safe_env if safe_env else None,
        )

        errlog = _get_stderr_log()

        async with stdio_client(server_params, errlog=errlog) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                with self._lock:
                    self._session = session
                    self._connected = True
                    self._error = None

                await self._discover_tools()
                self._ready.set()

                log.info(
                    "[MCP:%s] Connected, discovered %d tools",
                    self.name, len(self._tools),
                )

                await self._shutdown.wait()

    async def _discover_tools(self) -> None:
        """Fetch the tool listing from the MCP server."""
        if self._session is None:
            return
        tools_result = await self._session.list_tools()
        with self._lock:
            self._tools = (
                tools_result.tools
                if hasattr(tools_result, "tools")
                else []
            )

    # -- Tool calling -------------------------------------------------------

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the MCP server.  Returns result as JSON string."""
        with self._lock:
            session = self._session
            connected = self._connected

        if not connected or session is None:
            return json.dumps(
                {"error": f"MCP server '{self.name}' is not connected"},
                ensure_ascii=False,
            )

        try:
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            return json.dumps(
                {"error": f"MCP tool '{tool_name}' timed out "
                 f"after {self.timeout}s"},
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {"error": _sanitize_error(
                    f"MCP tool call failed: {exc}"
                )},
                ensure_ascii=False,
            )

        if result.isError:
            error_text = ""
            for block in (result.content or []):
                if hasattr(block, "text"):
                    error_text += block.text
            return json.dumps(
                {"error": _sanitize_error(
                    error_text or "MCP tool returned an error"
                )},
                ensure_ascii=False,
            )

        parts: list[str] = []
        for block in (result.content or []):
            if hasattr(block, "text"):
                parts.append(block.text)
        text_result = "\n".join(parts) if parts else ""

        return json.dumps({"result": text_result}, ensure_ascii=False)

    # -- Tool registration --------------------------------------------------

    def get_tool_schemas(self) -> list[dict]:
        """Return converted schemas for all discovered tools."""
        with self._lock:
            tools = list(self._tools)
        return [_convert_mcp_tool_schema(self.name, t) for t in tools]

    def register_all(self, registry: Any) -> int:
        """Register all discovered tools into the marneo ToolRegistry.

        Each tool is registered as a sync handler that delegates to
        call_tool() on the MCP background loop.

        Returns number of tools registered.
        """
        with self._lock:
            tools = list(self._tools)

        registered = 0
        for mcp_tool in tools:
            schema = _convert_mcp_tool_schema(self.name, mcp_tool)
            prefixed_name = schema["name"]

            existing = registry.get_entry(prefixed_name)
            if existing is not None:
                log.warning(
                    "[MCP:%s] Tool '%s' collides with existing -- skipping",
                    self.name, prefixed_name,
                )
                continue

            bridge_ref = self
            original_name = mcp_tool.name

            handler = _make_tool_handler(
                bridge_ref, original_name, bridge_ref.timeout
            )

            registry.register(
                name=prefixed_name,
                description=schema["description"],
                schema=schema,
                handler=handler,
                is_async=False,
                emoji="",
            )
            registered += 1
            log.debug(
                "[MCP:%s] Registered tool: %s", self.name, prefixed_name
            )

        with self._lock:
            self._registered_names = [
                _convert_mcp_tool_schema(self.name, t)["name"]
                for t in tools
            ]

        log.info("[MCP:%s] Registered %d tools", self.name, registered)
        return registered

    def status(self) -> dict[str, Any]:
        """Return a status dict for this bridge."""
        with self._lock:
            return {
                "name": self.name,
                "connected": self._connected,
                "tools": len(self._tools),
                "registered": len(self._registered_names),
                "error": self._error,
            }


def _make_tool_handler(
    bridge: McpBridge, tool_name: str, tool_timeout: float
) -> Any:
    """Create a sync handler that calls an MCP tool via the background loop.

    The handler conforms to the registry dispatch interface:
    handler(args_dict, **kwargs) -> str
    """
    def handler(args: dict, **kwargs: Any) -> str:
        with bridge._lock:
            session = bridge._session
            connected = bridge._connected
        if not connected or session is None:
            return json.dumps(
                {"error": f"MCP server '{bridge.name}' is not connected"},
                ensure_ascii=False,
            )

        async def _call() -> str:
            return await bridge.call_tool(tool_name, args)

        try:
            return _run_on_mcp_loop(_call(), timeout=tool_timeout)
        except concurrent.futures.TimeoutError:
            return json.dumps(
                {"error": f"MCP tool '{tool_name}' timed out "
                 f"after {tool_timeout}s"},
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {"error": _sanitize_error(str(exc))},
                ensure_ascii=False,
            )

    return handler


# ---------------------------------------------------------------------------
# McpManager -- manages multiple MCP server connections
# ---------------------------------------------------------------------------

class McpManager:
    """Manages multiple MCP server connections and registers their tools."""

    def __init__(self, registry: Any) -> None:
        self._bridges: dict[str, McpBridge] = {}
        self._registry = registry
        self._lock = threading.Lock()

    async def add_server(self, name: str, config: dict) -> bool:
        """Add and connect an MCP server from config.

        Config keys: command, args, env, timeout.
        Returns True if connection succeeded.
        """
        if not MCP_AVAILABLE:
            log.warning(
                "[MCP] Cannot add server '%s': mcp package not installed. "
                "Install with: pip install mcp",
                name,
            )
            return False

        command = config.get("command", "")
        args = config.get("args", [])
        env = config.get("env")
        timeout = int(config.get("timeout", _DEFAULT_TOOL_TIMEOUT))

        if not command:
            log.error("[MCP] Server '%s' has no command configured", name)
            return False

        bridge = McpBridge(
            name=name,
            command=command,
            args=args,
            env=env,
            timeout=timeout,
        )

        ok = await bridge.connect()
        if ok:
            bridge.register_all(self._registry)

        with self._lock:
            self._bridges[name] = bridge

        return ok

    async def remove_server(self, name: str) -> None:
        """Disconnect and remove an MCP server."""
        with self._lock:
            bridge = self._bridges.pop(name, None)
        if bridge:
            await bridge.disconnect()
            log.info("[MCP] Removed server '%s'", name)

    async def start_all(self, mcp_configs: dict[str, dict]) -> None:
        """Connect all configured MCP servers.

        Args:
            mcp_configs: Dict of {name: {command, args, env, timeout}}.
        """
        if not MCP_AVAILABLE:
            if mcp_configs:
                log.warning(
                    "[MCP] mcp_servers configured but mcp package "
                    "not installed. Install with: pip install mcp"
                )
            return

        if not mcp_configs:
            log.debug("[MCP] No MCP servers configured")
            return

        log.info("[MCP] Starting %d MCP server(s)...", len(mcp_configs))

        for name, config in mcp_configs.items():
            try:
                ok = await self.add_server(name, config)
                log.info(
                    "[MCP] Server '%s': %s",
                    name, "connected" if ok else "failed",
                )
            except Exception as exc:
                log.error(
                    "[MCP] Server '%s' startup error: %s", name, exc
                )

    async def stop_all(self) -> None:
        """Disconnect all servers."""
        with self._lock:
            names = list(self._bridges.keys())

        for name in names:
            try:
                await self.remove_server(name)
            except Exception as exc:
                log.warning(
                    "[MCP] Error stopping server '%s': %s", name, exc
                )

        log.info("[MCP] All servers stopped")

    def list_servers(self) -> list[dict]:
        """Return status of all connected servers."""
        with self._lock:
            bridges = list(self._bridges.values())
        return [b.status() for b in bridges]

    def get_bridge(self, name: str) -> Optional[McpBridge]:
        """Return a bridge by server name, or None."""
        with self._lock:
            return self._bridges.get(name)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_mcp_configs() -> dict[str, dict]:
    """Load mcp_servers section from ~/.marneo/config.yaml.

    Environment variable references (${VAR}) in env values are expanded.
    Returns empty dict if no MCP servers are configured.
    """
    try:
        from marneo.core.config import load_config
        cfg = load_config()
        raw_mcp = cfg.raw.get("mcp_servers", {})
        if not isinstance(raw_mcp, dict):
            return {}
        return raw_mcp
    except Exception as exc:
        log.warning("[MCP] Failed to load MCP config: %s", exc)
        return {}
