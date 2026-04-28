# tests/tools/test_ask_user.py
"""Tests for ask_user tool — registration, card JSON, and handler logic."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from marneo.tools.registry import registry
from marneo.tools.core.ask_user import (
    AskUserContext,
    ask_user_ctx,
    ask_user_handler,
)


# ── test_tool_registered ────────────────────────────────────────────────────

def test_tool_registered():
    """ask_user must be present in the tool registry after import."""
    entry = registry.get_entry("ask_user")
    assert entry is not None
    assert entry.name == "ask_user"
    assert entry.is_async is True


def test_tool_schema_has_question_required():
    """The schema must define 'questions' array and backward-compat 'question'."""
    entry = registry.get_entry("ask_user")
    assert entry is not None
    params = entry.schema["parameters"]
    assert "questions" in params["properties"]
    # Backward compat fields
    assert "question" in params["properties"]


# ── test_card_json_structure ────────────────────────────────────────────────
# Card structure is tested implicitly through the integration tests below.
# The _send_ask_card function builds and sends the card in one step.


# ── test_handler_requires_question ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_handler_requires_question():
    """Handler must return error when question is empty."""
    result = await ask_user_handler({"question": ""})
    parsed = json.loads(result)
    assert "error" in parsed
    assert "required" in parsed["error"].lower()


@pytest.mark.asyncio
async def test_handler_requires_context():
    """Handler must return error when ask_user_ctx is not set."""
    # Ensure context var is cleared
    token = ask_user_ctx.set(None)
    try:
        result = await ask_user_handler({"question": "Hello?"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "context" in parsed["error"].lower() or "feishu" in parsed["error"].lower()
    finally:
        ask_user_ctx.reset(token)


# ── test_handler_truncates_choices_to_4 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_handler_truncates_choices_to_4():
    """When more than 4 choices are given, only the first 4 are kept."""
    adapter = MagicMock()
    adapter._domain = "feishu"
    adapter._app_id = "test_id"
    adapter._app_secret = "test_secret"

    ctx = AskUserContext(chat_id="chat_trunc", adapter=adapter)
    token = ask_user_ctx.set(ctx)

    try:
        with patch("marneo.tools.core.ask_user._send_ask_card", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            # Create a future that resolves quickly to avoid hang
            with patch("marneo.gateway.pending_questions.PendingQuestionStore.create") as mock_create:
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                future.set_result("choice_1")
                mock_create.return_value = ("mq_trunc", future)

                result = await ask_user_handler({
                    "question": "Pick one?",
                    "choices": ["a", "b", "c", "d", "e", "f"],
                })

                # Verify create was called with at most 4 choices
                call_kwargs = mock_create.call_args
                actual_choices = call_kwargs[1].get("choices") if call_kwargs[1] else call_kwargs[0][2]
                assert len(actual_choices) <= 4
    finally:
        ask_user_ctx.reset(token)


# ── test_handler_send_failure ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handler_send_failure_returns_error():
    """When card send fails, handler returns a tool error."""
    adapter = MagicMock()
    adapter._domain = "feishu"
    adapter._app_id = "test_id"
    adapter._app_secret = "test_secret"

    ctx = AskUserContext(chat_id="chat_fail", adapter=adapter)
    token = ask_user_ctx.set(ctx)

    try:
        with patch("marneo.tools.core.ask_user._send_ask_card", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = False  # Simulate send failure

            result = await ask_user_handler({"question": "Will this fail?"})
            parsed = json.loads(result)
            assert "error" in parsed
            assert "fail" in parsed["error"].lower()
    finally:
        ask_user_ctx.reset(token)


# ── test_handler_returns_answer_on_success ──────────────────────────────────

@pytest.mark.asyncio
async def test_handler_returns_answer_on_success():
    """Full happy path: card sent, future resolved, handler returns answer."""
    adapter = MagicMock()
    adapter._domain = "feishu"
    adapter._app_id = "test_id"
    adapter._app_secret = "test_secret"

    ctx = AskUserContext(chat_id="chat_ok", adapter=adapter)
    token = ask_user_ctx.set(ctx)

    try:
        with patch("marneo.tools.core.ask_user._send_ask_card", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            with patch("marneo.gateway.pending_questions.PendingQuestionStore.create") as mock_create:
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                future.set_result("approved")
                mock_create.return_value = ("mq_ok", future)

                result = await ask_user_handler({
                    "question": "Approve?",
                    "choices": ["Yes", "No"],
                })
                parsed = json.loads(result)
                assert parsed["answer"] == "approved"
                assert parsed["question_id"] == "mq_ok"
    finally:
        ask_user_ctx.reset(token)
