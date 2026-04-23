# marneo/tools/registry.py
"""Tool registry — hermes-agent pattern adapted for marneo."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


def tool_result(**kwargs: Any) -> str:
    return json.dumps(kwargs, ensure_ascii=False, default=str)


def tool_error(message: str, **extra: Any) -> str:
    return json.dumps({"error": str(message), **extra}, ensure_ascii=False)


@dataclass
class ToolEntry:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable
    check_fn: Optional[Callable[[], bool]] = None
    is_async: bool = False
    emoji: str = ""
    max_result_chars: Optional[int] = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolEntry] = {}
        self._lock = threading.RLock()

    def register(
        self,
        name: str,
        description: str,
        schema: dict[str, Any],
        handler: Callable,
        check_fn: Optional[Callable[[], bool]] = None,
        is_async: bool = False,
        emoji: str = "",
        max_result_chars: Optional[int] = None,
    ) -> None:
        with self._lock:
            self._tools[name] = ToolEntry(
                name=name,
                description=description,
                schema=schema,
                handler=handler,
                check_fn=check_fn,
                is_async=is_async,
                emoji=emoji,
                max_result_chars=max_result_chars,
            )

    def get_entry(self, name: str) -> Optional[ToolEntry]:
        with self._lock:
            return self._tools.get(name)

    def get_definitions(self, names: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """Return OpenAI-format tool definitions for enabled tools."""
        with self._lock:
            entries = list(self._tools.values())

        if names is not None:
            entries = [e for e in entries if e.name in names]

        result = []
        for entry in entries:
            if entry.check_fn is not None:
                try:
                    if not entry.check_fn():
                        continue
                except Exception as exc:
                    log.warning("[Tools] check_fn for %r raised: %s", entry.name, exc)
                    continue
            result.append({"type": "function", "function": {**entry.schema, "name": entry.name}})
        return result

    def dispatch(self, name: str, args: dict[str, Any], **kwargs: Any) -> str:
        entry = self.get_entry(name)
        if entry is None:
            return tool_error(f"Unknown tool: {name}")
        try:
            if entry.is_async:
                result = _run_async(lambda: entry.handler(args, **kwargs))
            else:
                result = entry.handler(args, **kwargs)
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False, default=str)
            if entry.max_result_chars is not None and len(result) > entry.max_result_chars:
                result = json.dumps({"truncated": True, "content": result[:entry.max_result_chars]}, ensure_ascii=False)
            return result
        except Exception as exc:
            log.error("[Tools] %s dispatch error: %s", name, exc, exc_info=True)
            return tool_error(f"{type(exc).__name__}: {exc}")


def _run_async(coro_factory: Any) -> Any:
    """Run a coroutine factory from sync context.

    Accepts either a coroutine object OR a zero-arg callable that returns one.
    When called from within a running event loop, spawns a fresh thread with
    its own event loop to avoid cross-loop contamination.
    """
    import inspect
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        # Create the coroutine in the worker thread to avoid cross-loop issues
        if inspect.iscoroutine(coro_factory):
            # Already a coroutine — we can't avoid cross-loop, but wrap safely
            coro = coro_factory
        else:
            coro = None
        def _run() -> Any:
            c = coro if coro is not None else coro_factory()
            return asyncio.run(c)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            return future.result()
    if inspect.iscoroutine(coro_factory):
        return asyncio.run(coro_factory)
    return asyncio.run(coro_factory())


# Module-level singleton
registry = ToolRegistry()
