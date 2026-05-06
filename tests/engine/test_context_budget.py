"""Tests for ChatSession context-budget compaction behavior."""
import pytest
from unittest.mock import patch

from marneo.engine.chat import ChatEvent, ChatSession
from marneo.engine.provider import ResolvedProvider


@pytest.mark.asyncio
async def test_send_prunes_after_assistant_reply_exceeds_context_budget():
    session = ChatSession(context_budget_max_chars=80)

    async def fake_openai(provider):
        yield ChatEvent(type="text", content="assistant-" + "x" * 160)

    provider = ResolvedProvider(
        api_key="test",
        base_url="http://localhost",
        model="test-model",
        protocol="anthropic-compatible",
        provider_id="test",
    )
    with patch("marneo.engine.chat.resolve_provider", return_value=provider), \
         patch.object(session, "_call_anthropic", side_effect=fake_openai):
        events = []
        async for event in session.send("hello"):
            events.append(event)

    assert any(event.type == "text" for event in events)
    assert session._context_chars() <= session.context_budget_max_chars
    assert session.messages[0]["role"] == "system"
    assert "omitted" in session.messages[0]["content"].lower()


def test_context_budget_defaults_are_conservative_for_gateway_sessions():
    session = ChatSession()

    assert session.tool_result_context_max_chars <= 8_000
    assert session.context_budget_max_chars <= 50_000


def test_context_budget_does_not_leave_orphan_tool_messages():
    session = ChatSession(context_budget_max_chars=120)
    session.messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "please use tool"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "tool-1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "tool-1", "content": "x" * 500},
    ]

    session._prune_context_budget()

    for idx, message in enumerate(session.messages):
        if message.get("role") == "tool":
            assert idx > 0
            prev = session.messages[idx - 1]
            assert prev.get("role") == "assistant"
            assert prev.get("tool_calls")


@pytest.mark.asyncio
async def test_tool_enabled_first_call_prunes_after_appending_user_message():
    session = ChatSession(context_budget_max_chars=120)
    seen_context_chars: list[int] = []

    async def fake_call(provider, tool_defs):
        seen_context_chars.append(session._context_chars())
        yield ChatEvent(type="done")

    provider = ResolvedProvider(
        api_key="test",
        base_url="http://localhost",
        model="test-model",
        protocol="openai-compatible",
        provider_id="test",
    )
    with patch("marneo.engine.chat.resolve_provider", return_value=provider), \
         patch.object(session, "_call_openai_with_tools", side_effect=fake_call):
        events = []
        async for event in session._send_with_tool_defs("x" * 500, tool_defs=[]):
            events.append(event)

    assert any(event.type == "done" for event in events)
    assert seen_context_chars
    assert seen_context_chars[0] <= session.context_budget_max_chars
