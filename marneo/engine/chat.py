# marneo/engine/chat.py
"""Marneo chat engine — streaming conversation."""
from __future__ import annotations

import base64
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from marneo.engine.provider import resolve_provider, ResolvedProvider
from marneo.engine.json_repair import repair_json
from marneo.engine.token_tracker import TokenTracker

log = logging.getLogger(__name__)

_MAX_TEXT_INJECT = 200_000  # 200 KB max for text file inline injection
_LOOP_DETECT_THRESHOLD = 3  # consecutive identical tool calls before breaking


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
    import base64 as _b64  # noqa: F811 (stdlib, already at module level — kept for clarity)

    if not attachments:
        return text

    is_anthropic = (protocol == "anthropic-compatible")
    blocks: list[dict] = []
    _MAX_BINARY = 20 * 1024 * 1024  # 20 MB hard cap for binary attachments

    for att in attachments:
        data: bytes = att.get("data") or b""
        media_type: str = att.get("media_type") or ""
        filename: str = att.get("filename") or "file"

        if not data:
            continue

        # Guard oversized binary attachments before base64 encoding
        if len(data) > _MAX_BINARY and not media_type.startswith("text/"):
            blocks.append({"type": "text", "text": f"[文件过大: {filename} ({len(data)} 字节，超过20MB限制)]"})
            continue

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
    token_tracker: TokenTracker = field(default_factory=TokenTracker)

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
        _prev_call_sig: str = ""   # "name:args_json" of previous tool call
        _repeat_count: int = 0     # consecutive identical tool calls

        for _iteration in range(max_iterations):
            tool_calls_this_round: list[dict] = []

            # Pass attachments only on the first call
            call_attachments = attachments if _first_call else None
            async for event in self._send_with_tool_defs(call_text, tool_defs, call_attachments):
                if event.type == "tool_call":
                    try:
                        tool_calls_this_round.append(_json.loads(event.content))
                    except Exception as exc:
                        log.warning("[send_with_tools] Malformed tool_call JSON: %s", exc)
                        yield ChatEvent(type="error", content=f"Malformed tool_call JSON: {exc}")
                    yield event
                elif event.type != "done":
                    yield event

            # Robust ghost-message removal: match any empty user content (string or list)
            last = self.messages[-1] if self.messages else None
            if not call_text and last and last.get("role") == "user" and not last.get("content"):
                self.messages.pop()

            if not tool_calls_this_round:
                hit_limit = False
                break

            # ── Loop detection (openclaw pattern) ────────────────────────────
            call_sig = "|".join(
                f"{tc.get('name')}:{_json.dumps(tc.get('args', {}), sort_keys=True)}"
                for tc in tool_calls_this_round
            )
            if call_sig == _prev_call_sig:
                _repeat_count += 1
            else:
                _repeat_count = 1
                _prev_call_sig = call_sig

            if _repeat_count >= _LOOP_DETECT_THRESHOLD:
                log.warning("[send_with_tools] Loop detected: %s repeated %d times",
                            tool_calls_this_round[0].get("name"), _repeat_count)
                yield ChatEvent(type="error",
                                content=f"Tool loop detected: {tool_calls_this_round[0].get('name')} "
                                        f"called {_repeat_count} times with identical arguments")
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

    async def _send_with_tool_defs(
        self,
        user_text: str,
        tool_defs: list,
        attachments: "list[dict] | None" = None,
    ) -> AsyncIterator["ChatEvent"]:
        """Call LLM with tool definitions. Yields text and tool_call events."""
        import json as _json

        provider = resolve_provider()

        # Build content with attachments if any
        if user_text:
            content = _build_content_blocks(
                text=user_text,
                attachments=attachments or [],
                protocol=provider.protocol,
            )
            self.messages.append({"role": "user", "content": content})

        collected_text = ""
        tool_calls_raw: list[dict] = []

        try:
            if provider.protocol == "anthropic-compatible":
                async for event in self._call_anthropic_with_tools(provider, tool_defs):
                    if event.type == "text":
                        collected_text += event.content
                    elif event.type == "tool_call":
                        tool_calls_raw.append(_json.loads(event.content))
                    yield event
            else:
                async for event in self._call_openai_with_tools(provider, tool_defs):
                    if event.type == "text":
                        collected_text += event.content
                    elif event.type == "tool_call":
                        tool_calls_raw.append(_json.loads(event.content))
                    yield event

            # Append to history
            if collected_text:
                self.messages.append({"role": "assistant", "content": collected_text})
            if tool_calls_raw:
                self.messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": _json.dumps(tc.get("args", {}))},
                        }
                        for tc in tool_calls_raw
                    ],
                })

        except Exception as exc:
            log.error("Chat with tools error: %s", exc)
            yield ChatEvent(type="error", content=str(exc))

        yield ChatEvent(type="done")

    async def _call_openai_with_tools(
        self, provider: ResolvedProvider, tool_defs: list
    ) -> AsyncIterator["ChatEvent"]:
        """OpenAI-compatible streaming call with function calling."""
        import json as _json
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url)
        msgs: list[dict] = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.extend(self.messages)

        stream = await client.chat.completions.create(
            model=provider.model,
            messages=msgs,  # type: ignore[arg-type]
            tools=tool_defs,
            tool_choice="auto",
            max_tokens=4096,
            stream=True,
            stream_options={"include_usage": True},
        )

        tc_accum: dict[int, dict] = {}

        async for chunk in stream:
            if not chunk.choices:
                # Final chunk with usage stats (stream_options.include_usage)
                self.token_tracker.record_from_openai(provider.model, chunk)
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield ChatEvent(type="thinking", content=reasoning)
            if delta.content:
                yield ChatEvent(type="text", content=delta.content)
            for tc_delta in (delta.tool_calls or []):
                idx = tc_delta.index
                if idx not in tc_accum:
                    tc_accum[idx] = {"id": "", "name": "", "args": ""}
                if tc_delta.id:
                    tc_accum[idx]["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tc_accum[idx]["name"] += tc_delta.function.name
                    if tc_delta.function.arguments:
                        tc_accum[idx]["args"] += tc_delta.function.arguments

        for tc in tc_accum.values():
            try:
                args = _json.loads(repair_json(tc["args"])) if tc["args"] else {}
            except Exception:
                args = {}
            yield ChatEvent(type="tool_call", content=_json.dumps({
                "id": tc["id"], "name": tc["name"], "args": args
            }))

    async def _call_anthropic_with_tools(
        self, provider: ResolvedProvider, tool_defs: list
    ) -> AsyncIterator["ChatEvent"]:
        """Anthropic streaming call with tool_use blocks."""
        import json as _json
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=provider.api_key, base_url=provider.base_url)

        anthropic_tools = []
        for td in tool_defs:
            fn = td.get("function", {})
            anthropic_tools.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })

        kwargs: dict = {
            "model": provider.model,
            "max_tokens": 4096,
            "messages": list(self.messages),
            "tools": anthropic_tools,
        }
        if self.system_prompt:
            kwargs["system"] = self.system_prompt

        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                if text:
                    yield ChatEvent(type="text", content=text)

        final = await stream.get_final_message()
        for block in final.content:
            if hasattr(block, "type") and block.type == "tool_use":
                yield ChatEvent(type="tool_call", content=_json.dumps({
                    "id": block.id, "name": block.name, "args": block.input,
                }))

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
