# tests/tools/test_ask_user.py
"""Tests for ask_user tool (openclaw non-blocking pattern)."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from marneo.tools.registry import registry
from marneo.tools.core.ask_user import (
    AskUserContext,
    ask_user_ctx,
    ask_user_handler,
    build_ask_user_card,
    build_processing_card,
    build_answered_card,
    build_expired_card,
    update_card,
)


def test_tool_registered():
    entry = registry.get_entry("ask_user")
    assert entry is not None
    assert entry.is_async is True


def test_tool_schema_has_questions():
    entry = registry.get_entry("ask_user")
    params = entry.schema["parameters"]
    assert "questions" in params["properties"]


class TestCardBuilders:
    _QUESTIONS = [
        {"question": "Pick color?", "header": "Color", "options": [
            {"label": "Red", "description": "Warm"},
            {"label": "Blue", "description": "Cool"},
        ], "multiSelect": False},
    ]

    def test_ask_user_card_has_form(self):
        card = build_ask_user_card(self._QUESTIONS, "q1")
        assert card["header"]["template"] == "blue"
        body_elements = card["body"]["elements"]
        assert body_elements[0]["tag"] == "form"

    def test_ask_user_card_submit_button(self):
        card = build_ask_user_card(self._QUESTIONS, "q1")
        form_elems = card["body"]["elements"][0]["elements"]
        submit = [e for e in form_elems if e.get("tag") == "button"]
        assert len(submit) == 1
        assert "ask_user_submit_q1" in submit[0].get("name", "")

    def test_processing_card(self):
        card = build_processing_card(self._QUESTIONS, {"Pick color?": "Red"})
        assert card["header"]["template"] == "turquoise"

    def test_answered_card(self):
        card = build_answered_card(self._QUESTIONS, {"Pick color?": "Red"})
        assert card["header"]["template"] == "green"

    def test_expired_card(self):
        card = build_expired_card(self._QUESTIONS)
        assert card["header"]["template"] == "grey"


@pytest.mark.asyncio
async def test_update_card_uses_put_cardkit_endpoint(monkeypatch):
    """Card Kit card entity updates use PUT /cardkit/v1/cards/{card_id}.

    Feishu returns 404 for PATCH here, leaving expired/answered cards visually
    active even after the pending question is consumed.
    """
    adapter = MagicMock()
    adapter._domain = "feishu"

    calls = []

    class FakeResponse:
        def json(self):
            return {"code": 0, "msg": "ok"}

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def put(self, url, headers=None, content=None):
            calls.append(("PUT", url, headers, content))
            return FakeResponse()

        async def patch(self, url, headers=None, content=None):  # pragma: no cover - must not be used
            calls.append(("PATCH", url, headers, content))
            return FakeResponse()

    monkeypatch.setattr("marneo.tools.core.ask_user._get_tenant_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    ok = await update_card(adapter, "card123", build_expired_card(TestCardBuilders._QUESTIONS), 2)

    assert ok is True
    assert calls
    assert calls[0][0] == "PUT"
    assert calls[0][1].endswith("/cardkit/v1/cards/card123")
    payload = json.loads(calls[0][3])
    assert isinstance(payload["card"], dict)
    assert payload["card"]["type"] == "card_json"
    assert isinstance(payload["card"]["data"], str)


@pytest.mark.asyncio
async def test_handler_no_questions():
    result = await ask_user_handler({})
    parsed = json.loads(result)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_handler_no_context():
    token = ask_user_ctx.set(None)
    try:
        result = await ask_user_handler({"questions": [
            {"question": "test?", "header": "T", "options": [], "multiSelect": False}
        ]})
        parsed = json.loads(result)
        assert "error" in parsed
    finally:
        ask_user_ctx.reset(token)


@pytest.mark.asyncio
async def test_handler_returns_pending():
    """Non-blocking: handler returns {status: 'pending'} immediately."""
    adapter = MagicMock()
    adapter._domain = "feishu"
    adapter._app_id = "test_id"
    adapter._app_secret = "test_secret"
    adapter._loop = None

    ctx = AskUserContext(chat_id="chat1", adapter=adapter, sender_open_id="ou_test", msg_id="msg1")
    token = ask_user_ctx.set(ctx)

    try:
        with patch("marneo.tools.core.ask_user.create_card_entity", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = "card_123"
            with patch("marneo.tools.core.ask_user.send_card_by_card_id", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = True
                result = await ask_user_handler({"questions": [
                    {"question": "Approve?", "header": "Confirm", "options": [
                        {"label": "Yes", "description": "Approve"}, {"label": "No", "description": "Reject"}
                    ], "multiSelect": False}
                ]})
                parsed = json.loads(result)
                assert parsed["status"] == "pending"
                assert "questionId" in parsed or "question_id" in parsed
    finally:
        ask_user_ctx.reset(token)
