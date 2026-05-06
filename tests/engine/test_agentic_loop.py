# tests/engine/test_agentic_loop.py
"""Tests for the agentic tool-use loop in ChatSession."""
import json
import pytest
from unittest.mock import patch
from marneo.engine.chat import ChatSession, ChatEvent
from marneo.tools.registry import ToolRegistry, tool_result


@pytest.fixture
def registry_with_echo():
    reg = ToolRegistry()
    reg.register(
        name="echo",
        description="echo",
        schema={"name": "echo", "description": "echo", "parameters": {
            "type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]
        }},
        handler=lambda args, **kw: tool_result(msg=args["msg"]),
    )
    return reg


@pytest.mark.asyncio
async def test_send_with_tools_no_tool_call(registry_with_echo):
    """When LLM returns only text, stream it directly."""
    session = ChatSession(system_prompt="test")

    async def fake_tool_defs(text, tool_defs, attachments=None):
        yield ChatEvent(type="text", content="hello")
        yield ChatEvent(type="done")

    with patch.object(session, "_send_with_tool_defs", side_effect=fake_tool_defs):
        events = []
        async for e in session.send_with_tools("hi", registry=registry_with_echo):
            events.append(e)

    texts = [e.content for e in events if e.type == "text"]
    assert texts == ["hello"]


@pytest.mark.asyncio
async def test_send_with_tools_executes_tool_and_continues(registry_with_echo):
    """When LLM returns a tool_call, execute it and loop back."""
    session = ChatSession(system_prompt="test")
    call_count = 0

    async def fake_tool_defs(text, tool_defs, attachments=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield ChatEvent(type="tool_call", content=json.dumps({
                "id": "tc1", "name": "echo", "args": {"msg": "world"}
            }))
            yield ChatEvent(type="done")
        else:
            yield ChatEvent(type="text", content="done")
            yield ChatEvent(type="done")

    with patch.object(session, "_send_with_tool_defs", side_effect=fake_tool_defs):
        events = []
        async for e in session.send_with_tools("hi", registry=registry_with_echo):
            events.append(e)

    assert call_count == 2
    tool_result_events = [e for e in events if e.type == "tool_result"]
    assert len(tool_result_events) == 1
    assert "world" in tool_result_events[0].content
    text_events = [e for e in events if e.type == "text"]
    assert any("done" in e.content for e in text_events)


@pytest.mark.asyncio
async def test_send_with_tools_respects_max_iterations():
    """Loop stops after max_iterations even if LLM keeps calling tools."""
    reg = ToolRegistry()
    reg.register(
        name="loop_tool", description="", schema={"name": "loop_tool", "description": "",
        "parameters": {"type": "object", "properties": {}}},
        handler=lambda args, **kw: tool_result(ok=True),
    )
    session = ChatSession()

    async def always_calls_tool(text, tool_defs, attachments=None):
        yield ChatEvent(type="tool_call", content=json.dumps({"id": "t1", "name": "loop_tool", "args": {}}))
        yield ChatEvent(type="done")

    with patch.object(session, "_send_with_tool_defs", side_effect=always_calls_tool):
        events = []
        async for e in session.send_with_tools("go", registry=reg, max_iterations=3):
            events.append(e)

    tool_result_events = [e for e in events if e.type == "tool_result"]
    assert len(tool_result_events) <= 3


@pytest.mark.asyncio
async def test_loop_detection_does_not_emit_max_iterations_error_after_loop_error():
    """Loop detection is a terminal stop reason, not a max-iteration exhaustion."""
    reg = ToolRegistry()
    reg.register(
        name="loop_tool", description="", schema={"name": "loop_tool", "description": "",
        "parameters": {"type": "object", "properties": {}}},
        handler=lambda args, **kw: tool_result(ok=True),
    )
    session = ChatSession()

    async def always_calls_same_tool(text, tool_defs, attachments=None):
        yield ChatEvent(type="tool_call", content=json.dumps({"id": "t1", "name": "loop_tool", "args": {}}))
        yield ChatEvent(type="done")

    with patch.object(session, "_send_with_tool_defs", side_effect=always_calls_same_tool):
        events = []
        async for e in session.send_with_tools("go", registry=reg, max_iterations=20):
            events.append(e)

    errors = [e.content for e in events if e.type == "error"]
    assert any("Tool loop detected" in err for err in errors)
    assert not any("max_iterations reached" in err for err in errors)


@pytest.mark.asyncio
async def test_send_with_tools_no_registry_falls_back_to_send():
    """With no registry, falls back to plain send()."""
    session = ChatSession()

    async def fake_send(text, **kwargs):
        yield ChatEvent(type="text", content="plain response")
        yield ChatEvent(type="done")

    with patch.object(session, "send", side_effect=fake_send) as mock_send:
        events = []
        async for e in session.send_with_tools("hi", registry=None):
            events.append(e)

    texts = [e.content for e in events if e.type == "text"]
    assert "plain response" in texts


@pytest.mark.asyncio
async def test_send_with_tools_truncates_large_tool_result_before_injecting_context():
    reg = ToolRegistry()
    huge = "x" * 1000
    reg.register(
        name="huge_tool",
        description="huge",
        schema={"name": "huge_tool", "description": "huge", "parameters": {"type": "object", "properties": {}}},
        handler=lambda args, **kw: huge,
    )
    session = ChatSession(tool_result_context_max_chars=120)
    call_count = 0
    second_round_tool_context = ""

    async def fake_tool_defs(text, tool_defs, attachments=None):
        nonlocal call_count, second_round_tool_context
        call_count += 1
        if call_count == 1:
            yield ChatEvent(type="tool_call", content=json.dumps({"id": "tc1", "name": "huge_tool", "args": {}}))
            yield ChatEvent(type="done")
        else:
            tool_msgs = [m for m in session.messages if m.get("role") == "tool"]
            second_round_tool_context = tool_msgs[-1]["content"]
            yield ChatEvent(type="text", content="done")
            yield ChatEvent(type="done")

    with patch.object(session, "_send_with_tool_defs", side_effect=fake_tool_defs):
        events = []
        async for e in session.send_with_tools("hi", registry=reg):
            events.append(e)

    tool_events = [e for e in events if e.type == "tool_result"]
    assert tool_events[0].content == huge
    assert len(second_round_tool_context) <= 120
    assert "truncated" in second_round_tool_context.lower()
    assert "original_chars=1000" in second_round_tool_context


def test_prune_context_budget_keeps_system_and_recent_messages():
    session = ChatSession(context_budget_max_chars=220)
    session.messages = [
        {"role": "user", "content": "old-user-" + "a" * 120},
        {"role": "assistant", "content": "old-assistant-" + "b" * 120},
        {"role": "tool", "content": "old-tool-" + "c" * 120},
        {"role": "user", "content": "recent-user"},
        {"role": "assistant", "content": "recent-assistant"},
    ]

    session._prune_context_budget()

    assert len(session.messages) < 5
    assert session.messages[-2]["content"] == "recent-user"
    assert session.messages[-1]["content"] == "recent-assistant"
    assert session.messages[0]["role"] == "system"
    assert "omitted" in session.messages[0]["content"].lower()
