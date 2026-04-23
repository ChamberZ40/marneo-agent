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

    async def send_with_tools(
        self,
        user_text: str,
        registry: Any = None,
        max_iterations: int = 20,
    ) -> AsyncIterator["ChatEvent"]:
        """Agentic loop: send → execute tool calls → loop until LLM returns text.

        Yields ChatEvent types: text, thinking, tool_call, tool_result, error, done.
        Falls back to plain send() when registry is None or has no tools.
        """
        import json as _json

        if registry is None:
            async for event in self.send(user_text):
                yield event
            return

        tool_defs = registry.get_definitions()
        if not tool_defs:
            async for event in self.send(user_text):
                yield event
            return

        # First call uses user_text; subsequent calls use "" (tool results already in history)
        call_text = user_text

        for _iteration in range(max_iterations):
            tool_calls_this_round: list[dict] = []

            async for event in self.send(call_text):
                if event.type == "tool_call":
                    try:
                        tool_calls_this_round.append(_json.loads(event.content))
                    except Exception:
                        pass
                    yield event
                elif event.type != "done":
                    yield event

            if not tool_calls_this_round:
                break

            # Execute tools and inject results into history for next LLM call
            for tc in tool_calls_this_round:
                name = tc.get("name", "")
                args = tc.get("args", {})
                tc_id = tc.get("id", "")
                result = registry.dispatch(name, args)
                yield ChatEvent(type="tool_result", content=result)
                # Inject as tool message so LLM sees the result
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result,
                })

            call_text = ""  # subsequent iterations: history has tool results

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
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
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
