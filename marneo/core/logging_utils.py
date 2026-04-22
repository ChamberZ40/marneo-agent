# marneo/core/logging_utils.py
"""Structured logging utilities for marneo."""
from __future__ import annotations
import logging
from typing import Any


class ContextLogger:
    """Logger wrapper that includes context fields in every message."""

    def __init__(self, name: str, **context: Any) -> None:
        self._logger = logging.getLogger(name)
        self._context = context

    def _fmt(self, msg: str) -> str:
        if not self._context:
            return msg
        ctx_str = " ".join(f"{k}={v}" for k, v in self._context.items())
        return f"[{ctx_str}] {msg}"

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.info(self._fmt(msg), *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.error(self._fmt(msg), *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.warning(self._fmt(msg), *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.debug(self._fmt(msg), *args, **kwargs)

    def bind(self, **extra: Any) -> "ContextLogger":
        """Return new logger with additional context."""
        return ContextLogger(self._logger.name, **{**self._context, **extra})


def get_logger(name: str, **context: Any) -> ContextLogger:
    """Get a context-aware logger."""
    return ContextLogger(name, **context)
