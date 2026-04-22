# marneo/engine/chat.py
"""Marneo chat engine — streaming conversation."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from marneo.engine.provider import resolve_provider, ResolvedProvider

log = logging.getLogger(__name__)


@dataclass
class ChatEvent:
    type: str   # "text" | "thinking" | "error" | "done"
    content: str = ""


@dataclass
class ChatSession:
    """Maintains conversation history for one session."""
    messages: list[dict[str, Any]] = field(default_factory=list)
    system_prompt: str = ""

    def clear(self) -> None:
        self.messages.clear()

    async def send(self, user_text: str) -> AsyncIterator[ChatEvent]:
        """Stream events for a user message."""
        self.messages.append({"role": "user", "content": user_text})
        provider = resolve_provider()
        collected = ""

        try:
            if provider.protocol == "anthropic-compatible":
                async for event in self._call_anthropic(provider):
                    if event.type == "text" and event.content:
                        collected += event.content
                    yield event
            else:
                async for event in self._call_openai(provider):
                    if event.type == "text" and event.content:
                        collected += event.content
                    yield event

            if collected:
                self.messages.append({"role": "assistant", "content": collected})

        except Exception as exc:
            log.error("Chat error: %s", exc)
            yield ChatEvent(type="error", content=str(exc))

        yield ChatEvent(type="done")

    async def _call_openai(self, provider: ResolvedProvider) -> AsyncIterator[ChatEvent]:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url)

        msgs: list[dict] = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.extend(self.messages)

        stream = await client.chat.completions.create(
            model=provider.model,
            messages=msgs,
            max_tokens=4096,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    yield ChatEvent(type="thinking", content=reasoning)
                if delta.content:
                    yield ChatEvent(type="text", content=delta.content)

    async def _call_anthropic(self, provider: ResolvedProvider) -> AsyncIterator[ChatEvent]:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=provider.api_key, base_url=provider.base_url)

        msgs = list(self.messages)
        kwargs: dict[str, Any] = {
            "model": provider.model,
            "max_tokens": 4096,
            "messages": msgs,
        }
        if self.system_prompt:
            kwargs["system"] = self.system_prompt

        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                if text:
                    yield ChatEvent(type="text", content=text)
