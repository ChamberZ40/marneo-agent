"""Tests for OpenAI-compatible ChatSession calls."""
import logging
from types import SimpleNamespace

import pytest

from marneo.engine.chat import ChatEvent, ChatSession
from marneo.engine.provider import ResolvedProvider


class FakeOpenAIStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class FakeOpenAIClient:
    calls: list[dict] = []
    init_kwargs: list[dict] = []

    def __init__(self, **kwargs):
        self.init_kwargs.append(kwargs)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeOpenAIStream([
            SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            reasoning_content="thinking...",
                            content=None,
                            tool_calls=None,
                        )
                    )
                ],
            ),
            SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            reasoning_content=None,
                            content="hello",
                            tool_calls=None,
                        )
                    )
                ],
            ),
            SimpleNamespace(
                usage=SimpleNamespace(
                    prompt_tokens=7,
                    completion_tokens=3,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=2),
                ),
                choices=[],
            ),
        ])


@pytest.mark.asyncio
async def test_send_uses_openai_compatible_stream_without_tools(monkeypatch):
    FakeOpenAIClient.calls = []
    FakeOpenAIClient.init_kwargs = []
    monkeypatch.setattr("openai.AsyncOpenAI", FakeOpenAIClient)
    provider = ResolvedProvider(
        api_key="test-key",
        base_url="http://provider.local/v1",
        model="test-model",
        protocol="openai-compatible",
        provider_id="test-provider",
    )
    monkeypatch.setattr("marneo.engine.chat.resolve_provider", lambda: provider)

    session = ChatSession(system_prompt="system prompt")

    events = []
    async for event in session.send("hello user"):
        events.append(event)

    assert [(event.type, event.content) for event in events] == [
        ("thinking", "thinking..."),
        ("text", "hello"),
        ("done", ""),
    ]
    assert session.messages[-1] == {"role": "assistant", "content": "hello"}
    assert FakeOpenAIClient.init_kwargs == [
        {
            "api_key": "test-key",
            "base_url": "http://provider.local/v1",
            "timeout": 60.0,
            "max_retries": 1,
        }
    ]
    assert FakeOpenAIClient.calls == [
        {
            "model": "test-model",
            "messages": [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "hello user"},
            ],
            "max_tokens": 4096,
            "stream": True,
        }
    ]
    assert session.token_tracker.summary()["by_model"]["test-model"] == {
        "calls": 1,
        "input": 7,
        "output": 3,
    }


class NoToolRegistry:
    def get_definitions(self):
        return []


class OneToolRegistry:
    def get_definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "noop",
                    "description": "No-op tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]


@pytest.mark.asyncio
async def test_send_with_tools_logs_fallback_when_registry_has_no_tools(monkeypatch, caplog):
    provider = ResolvedProvider(
        api_key="test-key",
        base_url="http://provider.local/v1",
        model="test-model",
        protocol="openai-compatible",
        provider_id="test-provider",
    )
    monkeypatch.setattr("marneo.engine.chat.resolve_provider", lambda: provider)

    async def fake_call_openai(provider):
        yield ChatEvent(type="text", content="plain reply")

    session = ChatSession()
    monkeypatch.setattr(session, "_call_openai", fake_call_openai)

    with caplog.at_level(logging.INFO, logger="marneo.engine.chat"):
        events = []
        async for event in session.send_with_tools("hello", registry=NoToolRegistry()):
            events.append(event)

    assert [(event.type, event.content) for event in events] == [
        ("text", "plain reply"),
        ("done", ""),
    ]
    assert any(
        "No tool definitions available; falling back to plain send" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_send_with_tools_logs_tool_loop_start(monkeypatch, caplog):
    provider = ResolvedProvider(
        api_key="test-key",
        base_url="http://provider.local/v1",
        model="test-model",
        protocol="openai-compatible",
        provider_id="test-provider",
    )
    monkeypatch.setattr("marneo.engine.chat.resolve_provider", lambda: provider)

    async def fake_call_openai_with_tools(provider, tool_defs):
        yield ChatEvent(type="text", content="tool-aware reply")

    session = ChatSession()
    monkeypatch.setattr(session, "_call_openai_with_tools", fake_call_openai_with_tools)

    with caplog.at_level(logging.INFO, logger="marneo.engine.chat"):
        events = []
        async for event in session.send_with_tools(
            "hello",
            registry=OneToolRegistry(),
            max_iterations=2,
        ):
            events.append(event)

    assert [(event.type, event.content) for event in events] == [
        ("text", "tool-aware reply"),
        ("done", ""),
    ]
    assert any(
        "Starting tool loop: tool_count=1 max_iterations=2" in record.getMessage()
        for record in caplog.records
    )
