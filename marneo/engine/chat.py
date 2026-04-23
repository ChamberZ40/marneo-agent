# marneo/engine/chat.py
"""Marneo chat engine — streaming conversation."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from marneo.engine.provider import resolve_provider, ResolvedProvider

log = logging.getLogger(__name__)

_MAX_TEXT_INJECT = 200_000  # 200 KB max for text file inline injection


def _build_content_blocks(
    text: str,
    attachments: list[dict],
    protocol: str,
) -> "str | list[dict]":
    """Build LLM content from text + attachments.

    Returns plain string when no attachments have data.
    Returns list of content blocks when attachments are present.

    OpenAI format:   [{"type": "text", ...}, {"type": "image_url", ...}]
    Anthropic format:[{"type": "text", ...}, {"type": "image", "source": {...}}]
    """
    import base64 as _b64

    if not attachments:
        return text

    is_anthropic = (protocol == "anthropic-compatible")
    blocks: list[dict] = []

    for att in attachments:
        data: bytes = att.get("data") or b""
        media_type: str = att.get("media_type") or ""
        filename: str = att.get("filename") or "file"

        if not data:
            continue  # skip empty attachments

        b64 = _b64.b64encode(data).decode()

        # ── Plain text files → inject content as text ─────────────────────
        if media_type.startswith("text/") or media_type == "application/json":
            try:
                file_text = data.decode("utf-8", errors="replace")
                if len(file_text) > _MAX_TEXT_INJECT:
                    file_text = file_text[:_MAX_TEXT_INJECT] + "\n... (truncated)"
                blocks.append({"type": "text", "text": f"[Content of {filename}]:\n{file_text}"})
            except Exception:
                blocks.append({"type": "text", "text": f"[文件: {filename}]"})
            continue

        # ── Images ────────────────────────────────────────────────────────
        if media_type.startswith("image/"):
            if is_anthropic:
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                })
            else:
                blocks.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{b64}"},
                })
            continue

        # ── PDF ───────────────────────────────────────────────────────────
        if media_type == "application/pdf":
            if is_anthropic:
                blocks.append({
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
                })
            else:
                # OpenAI/MiniMax: no native PDF block → inject text notice
                blocks.append({
                    "type": "text",
                    "text": f"[PDF文件: {filename}，共 {len(data)} 字节。注意：这是PDF格式文档。]",
                })
            continue

        # ── Other binary (DOCX, XLSX, etc.) ──────────────────────────────
        blocks.append({"type": "text", "text": f"[文件: {filename} ({media_type})]"})

    if not blocks:
        return text  # all attachments were empty, fall back to plain text

    # Prepend user text as first block (if non-empty)
    if text.strip():
        blocks.insert(0, {"type": "text", "text": text})

    return blocks


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

    async def send(
        self,
        user_text: str,
        attachments: "list[dict] | None" = None,
    ) -> AsyncIterator[ChatEvent]:
        """Stream events for a user message."""
        provider = resolve_provider()
        content = _build_content_blocks(
            text=user_text,
            attachments=attachments or [],
            protocol=provider.protocol,
        )
        self.messages.append({"role": "user", "content": content})
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
        attachments: "list[dict] | None" = None,
    ) -> AsyncIterator["ChatEvent"]:
        """Agentic loop: send → execute tool calls → loop until LLM returns text.

        Yields ChatEvent types: text, thinking, tool_call, tool_result, error, done.
        Falls back to plain send() when registry is None or has no tools.
        """
        import json as _json

        if registry is None:
            async for event in self.send(user_text, attachments=attachments):
                yield event
            return

        tool_defs = registry.get_definitions()
        if not tool_defs:
            async for event in self.send(user_text, attachments=attachments):
                yield event
            return

        # First call uses user_text; subsequent iterations skip the user append
        # by directly calling the LLM with existing history (tool results already injected)
        call_text = user_text
        hit_limit = True
        _first_call = True

        for _iteration in range(max_iterations):
            tool_calls_this_round: list[dict] = []

            # Pass attachments only on the first call
            call_attachments = attachments if _first_call else None
            async for event in self.send(call_text, attachments=call_attachments):
                if event.type == "tool_call":
                    try:
                        tool_calls_this_round.append(_json.loads(event.content))
                    except Exception as exc:
                        log.warning("[send_with_tools] Malformed tool_call JSON: %s", exc)
                        yield ChatEvent(type="error", content=f"Malformed tool_call JSON: {exc}")
                    yield event
                elif event.type != "done":
                    yield event

            # Fix: remove ghost empty user message injected by send("") on iterations > 0
            if not call_text and self.messages and self.messages[-1] == {"role": "user", "content": ""}:
                self.messages.pop()

            if not tool_calls_this_round:
                hit_limit = False
                break

            # Execute tools and inject results into history for next LLM call
            for tc in tool_calls_this_round:
                name = tc.get("name", "")
                args = tc.get("args", {})
                tc_id = tc.get("id", "")
                result = registry.dispatch(name, args)
                yield ChatEvent(type="tool_result", content=result)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result,
                })

            call_text = ""  # subsequent iterations: tool results already in history
            _first_call = False

        if hit_limit:
            yield ChatEvent(type="error", content="max_iterations reached without final text response")

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
            messages=msgs,  # type: ignore[arg-type]
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
