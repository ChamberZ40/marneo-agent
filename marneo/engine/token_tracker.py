# marneo/engine/token_tracker.py
"""Track token usage per session for cost monitoring.

Captures input/output/cache tokens from both OpenAI and Anthropic API responses.
Hermes-agent pattern: per-session aggregation with provider/model breakdown.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_calls: int = 0


@dataclass
class TokenTracker:
    """Accumulates token usage for a session."""

    _by_model: dict[str, TokenUsage] = field(default_factory=dict)
    _start_time: float = field(default_factory=time.time)

    def record(self, model: str, input_tokens: int = 0, output_tokens: int = 0,
               cache_read: int = 0, cache_write: int = 0) -> None:
        if model not in self._by_model:
            self._by_model[model] = TokenUsage()
        u = self._by_model[model]
        u.input_tokens += input_tokens
        u.output_tokens += output_tokens
        u.cache_read_tokens += cache_read
        u.cache_write_tokens += cache_write
        u.total_calls += 1

    def record_from_openai(self, model: str, response: Any) -> None:
        """Extract usage from an OpenAI-compatible response or chunk."""
        usage = getattr(response, "usage", None)
        if not usage:
            return
        details = getattr(usage, "prompt_tokens_details", None)
        cached = 0
        if details and hasattr(details, "get"):
            cached = details.get("cached_tokens", 0) or 0
        elif details and hasattr(details, "cached_tokens"):
            cached = getattr(details, "cached_tokens", 0) or 0
        self.record(
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cache_read=cached,
        )

    def record_from_anthropic(self, model: str, response: Any) -> None:
        """Extract usage from an Anthropic message response."""
        usage = getattr(response, "usage", None)
        if not usage:
            return
        self.record(
            model=model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )

    @property
    def total(self) -> TokenUsage:
        t = TokenUsage()
        for u in self._by_model.values():
            t.input_tokens += u.input_tokens
            t.output_tokens += u.output_tokens
            t.cache_read_tokens += u.cache_read_tokens
            t.cache_write_tokens += u.cache_write_tokens
            t.total_calls += u.total_calls
        return t

    def summary(self) -> dict:
        t = self.total
        return {
            "total_calls": t.total_calls,
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "cache_read_tokens": t.cache_read_tokens,
            "cache_write_tokens": t.cache_write_tokens,
            "session_duration_seconds": int(time.time() - self._start_time),
            "by_model": {
                model: {
                    "calls": u.total_calls,
                    "input": u.input_tokens,
                    "output": u.output_tokens,
                }
                for model, u in self._by_model.items()
            },
        }
