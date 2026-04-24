# tests/engine/test_tool_calling.py
"""Integration tests for the tool calling internals:
_send_with_tool_defs, _call_openai_with_tools, and the full agentic loop.

These tests verify the INTERNAL behavior of the tool calling pipeline,
complementing test_agentic_loop.py which mocks _send_with_tool_defs.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from marneo.engine.chat import ChatEvent, ChatSession
from marneo.engine.provider import ResolvedProvider
from marneo.tools.registry import ToolRegistry, tool_result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_PROVIDER = ResolvedProvider(
    api_key="test-key",
    base_url="https://fake.api/v1",
    model="test-model",
    protocol="openai-compatible",
    provider_id="test",
)


@pytest.fixture
def registry_with_echo():
    reg = ToolRegistry()
    reg.register(
        name="echo",
        description="Echo the message back",
        schema={
            "name": "echo",
            "description": "Echo the message back",
            "parameters": {
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
        },
        handler=lambda args, **kw: tool_result(msg=args["msg"]),
    )
    return reg


# ---------------------------------------------------------------------------
# Helpers for building mock streaming chunks
# ---------------------------------------------------------------------------

def _text_chunk(text: str):
    """Build a mock OpenAI streaming chunk with text content."""
    delta = SimpleNamespace(content=text, tool_calls=None, reasoning_content=None)
    choice = SimpleNamespace(delta=delta)
    return SimpleNamespace(choices=[choice])


def _tool_call_chunk(index: int, tc_id: str = "", name: str = "", arguments: str = ""):
    """Build a mock OpenAI streaming chunk with a tool_call delta."""
    fn = SimpleNamespace(name=name or None, arguments=arguments or None)
    tc_delta = SimpleNamespace(index=index, id=tc_id or None, function=fn)
    delta = SimpleNamespace(content=None, tool_calls=[tc_delta], reasoning_content=None)
    choice = SimpleNamespace(delta=delta)
    return SimpleNamespace(choices=[choice])


def _empty_chunk():
    """Chunk with no choices (heartbeat)."""
    return SimpleNamespace(choices=[])


class MockAsyncStream:
    """Async iterator over a list of chunks."""

    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


# ---------------------------------------------------------------------------
# 1. _send_with_tool_defs passes tools to _call_openai_with_tools
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_with_tool_defs_passes_tools_to_openai(registry_with_echo):
    """Verify that _send_with_tool_defs calls _call_openai_with_tools
    with the correct tool definitions when the provider is openai-compatible."""
    session = ChatSession(system_prompt="test")
    tool_defs = registry_with_echo.get_definitions()

    captured_tool_defs = []

    async def fake_call(provider, td):
        captured_tool_defs.append(td)
        yield ChatEvent(type="text", content="hi")

    with patch.object(session, "_call_openai_with_tools", side_effect=fake_call), \
         patch("marneo.engine.chat.resolve_provider", return_value=FAKE_PROVIDER):
        events = []
        async for e in session._send_with_tool_defs("hello", tool_defs):
            events.append(e)

    assert len(captured_tool_defs) == 1
    assert captured_tool_defs[0] is tool_defs


# ---------------------------------------------------------------------------
# 2. _call_openai_with_tools parses streaming tool_call deltas
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_openai_with_tools_parses_streaming_tool_call_deltas():
    """Mock OpenAI streaming response to return tool_call deltas,
    verify they are accumulated and yielded as tool_call events."""
    session = ChatSession(system_prompt="test")

    chunks = [
        _tool_call_chunk(0, tc_id="call_123", name="echo", arguments=""),
        _tool_call_chunk(0, arguments='{"msg"'),
        _tool_call_chunk(0, arguments=': "hello"}'),
        _empty_chunk(),
    ]

    mock_create = AsyncMock(return_value=MockAsyncStream(chunks))
    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        events = []
        async for e in session._call_openai_with_tools(FAKE_PROVIDER, [{"type": "function", "function": {"name": "echo"}}]):
            events.append(e)

    tool_events = [e for e in events if e.type == "tool_call"]
    assert len(tool_events) == 1
    payload = json.loads(tool_events[0].content)
    assert payload["id"] == "call_123"
    assert payload["name"] == "echo"
    assert payload["args"] == {"msg": "hello"}


# ---------------------------------------------------------------------------
# 3. _call_openai_with_tools — text-only response yields only text events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_openai_with_tools_text_only_response():
    """When the LLM returns only text (no tool calls), only text events are yielded."""
    session = ChatSession()

    chunks = [
        _text_chunk("Hello "),
        _text_chunk("world!"),
    ]

    mock_create = AsyncMock(return_value=MockAsyncStream(chunks))
    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        events = []
        async for e in session._call_openai_with_tools(FAKE_PROVIDER, []):
            events.append(e)

    assert all(e.type == "text" for e in events)
    combined = "".join(e.content for e in events)
    assert combined == "Hello world!"


# ---------------------------------------------------------------------------
# 4. _send_with_tool_defs appends user message to history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_with_tool_defs_appends_user_message_to_history():
    """Verify user message is appended to self.messages before calling LLM."""
    session = ChatSession()
    assert len(session.messages) == 0

    async def fake_call(provider, td):
        yield ChatEvent(type="text", content="ok")

    with patch.object(session, "_call_openai_with_tools", side_effect=fake_call), \
         patch("marneo.engine.chat.resolve_provider", return_value=FAKE_PROVIDER):
        async for _ in session._send_with_tool_defs("test input", []):
            pass

    user_msgs = [m for m in session.messages if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0]["content"] == "test input"


# ---------------------------------------------------------------------------
# 5. _send_with_tool_defs appends assistant message after text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_with_tool_defs_appends_assistant_message_after_text():
    """Verify assistant response is appended to history after text collection."""
    session = ChatSession()

    async def fake_call(provider, td):
        yield ChatEvent(type="text", content="response text")

    with patch.object(session, "_call_openai_with_tools", side_effect=fake_call), \
         patch("marneo.engine.chat.resolve_provider", return_value=FAKE_PROVIDER):
        async for _ in session._send_with_tool_defs("hi", []):
            pass

    assistant_msgs = [m for m in session.messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == "response text"


# ---------------------------------------------------------------------------
# 6. _send_with_tool_defs appends tool_call message in OpenAI format
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_with_tool_defs_appends_tool_call_message_after_tool_calls():
    """Verify tool_calls are appended to history in correct OpenAI format."""
    session = ChatSession()

    tc_payload = json.dumps({"id": "tc_42", "name": "echo", "args": {"msg": "hi"}})

    async def fake_call(provider, td):
        yield ChatEvent(type="tool_call", content=tc_payload)

    with patch.object(session, "_call_openai_with_tools", side_effect=fake_call), \
         patch("marneo.engine.chat.resolve_provider", return_value=FAKE_PROVIDER):
        async for _ in session._send_with_tool_defs("run tool", []):
            pass

    assistant_msgs = [m for m in session.messages if m["role"] == "assistant" and m.get("tool_calls")]
    assert len(assistant_msgs) == 1
    tc = assistant_msgs[0]["tool_calls"][0]
    assert tc["id"] == "tc_42"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "echo"
    assert json.loads(tc["function"]["arguments"]) == {"msg": "hi"}


# ---------------------------------------------------------------------------
# 7. send_with_tools full loop: tool call -> execute -> text -> done
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_with_tools_full_loop_tool_then_text(registry_with_echo):
    """Verify the full agentic loop: first call returns tool_call, tool is
    executed, second call returns text, loop ends."""
    session = ChatSession(system_prompt="test")
    call_count = 0

    async def fake_tool_defs(text, tool_defs, attachments=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield ChatEvent(type="tool_call", content=json.dumps({
                "id": "tc_1", "name": "echo", "args": {"msg": "ping"},
            }))
            yield ChatEvent(type="done")
        else:
            yield ChatEvent(type="text", content="final answer")
            yield ChatEvent(type="done")

    with patch.object(session, "_send_with_tool_defs", side_effect=fake_tool_defs):
        events = []
        async for e in session.send_with_tools("go", registry=registry_with_echo):
            events.append(e)

    # Two LLM calls: tool_call round + text round
    assert call_count == 2

    # One tool_result event from echo execution
    tool_results = [e for e in events if e.type == "tool_result"]
    assert len(tool_results) == 1
    assert "ping" in tool_results[0].content

    # Final text
    text_events = [e for e in events if e.type == "text"]
    assert any("final answer" in e.content for e in text_events)

    # Loop ends with done
    assert events[-1].type == "done"


# ---------------------------------------------------------------------------
# 8. send_with_tools injects tool result into history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_with_tools_tool_result_injected_into_history(registry_with_echo):
    """After tool execution, verify {"role": "tool", "tool_call_id": ...,
    "content": ...} is in messages."""
    session = ChatSession()
    call_count = 0

    async def fake_tool_defs(text, tool_defs, attachments=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield ChatEvent(type="tool_call", content=json.dumps({
                "id": "tc_99", "name": "echo", "args": {"msg": "data"},
            }))
            yield ChatEvent(type="done")
        else:
            yield ChatEvent(type="text", content="ok")
            yield ChatEvent(type="done")

    with patch.object(session, "_send_with_tool_defs", side_effect=fake_tool_defs):
        async for _ in session.send_with_tools("run", registry=registry_with_echo):
            pass

    tool_msgs = [m for m in session.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "tc_99"
    assert "data" in tool_msgs[0]["content"]
