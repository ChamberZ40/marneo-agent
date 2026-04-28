# tests/gateway/test_pending_questions.py
"""Tests for pending question registry (openclaw non-blocking pattern)."""
from marneo.gateway.pending_questions import (
    PendingQuestionContext,
    store_pending_question,
    consume_pending_question,
    get_pending_question,
    find_question_by_chat,
    read_form_text_field,
    read_form_multi_select,
    get_input_field_name,
    get_select_field_name,
    _pending_questions,
    _by_chat_context,
    _lock,
)


def _clear():
    with _lock:
        _pending_questions.clear()
        _by_chat_context.clear()


def _make_ctx(qid="q1", chat_id="chat1", account_id="app1", **kw):
    return PendingQuestionContext(
        question_id=qid, chat_id=chat_id, account_id=account_id,
        sender_open_id=kw.get("sender", "ou_test"),
        card_id=kw.get("card_id", "card1"),
        questions=kw.get("questions", [{"question": "test?", "header": "Test", "options": [], "multiSelect": False}]),
        message_id=kw.get("msg_id", "msg1"),
    )


class TestStoreAndConsume:
    def setup_method(self):
        _clear()

    def test_store_and_get(self):
        ctx = _make_ctx()
        store_pending_question(ctx)
        assert get_pending_question("q1") is ctx

    def test_consume_returns_ctx(self):
        store_pending_question(_make_ctx())
        assert consume_pending_question("q1") is not None
        assert get_pending_question("q1") is None

    def test_consume_nonexistent(self):
        assert consume_pending_question("nope") is None

    def test_double_consume(self):
        store_pending_question(_make_ctx())
        consume_pending_question("q1")
        assert consume_pending_question("q1") is None


class TestFindByChat:
    def setup_method(self):
        _clear()

    def test_find_single(self):
        ctx = _make_ctx()
        store_pending_question(ctx)
        assert find_question_by_chat("app1", "chat1") is ctx

    def test_find_none(self):
        assert find_question_by_chat("app1", "chat1") is None

    def test_ambiguous_returns_none(self):
        store_pending_question(_make_ctx(qid="q1"))
        store_pending_question(_make_ctx(qid="q2"))
        assert find_question_by_chat("app1", "chat1") is None

    def test_skips_submitted(self):
        ctx = _make_ctx()
        ctx.submitted = True
        store_pending_question(ctx)
        assert find_question_by_chat("app1", "chat1") is None


class TestFormValueParsers:
    def test_read_text_field(self):
        assert read_form_text_field({"answer_0": "hello"}, "answer_0") == "hello"

    def test_read_text_empty(self):
        assert read_form_text_field({"answer_0": ""}, "answer_0") is None

    def test_read_text_missing(self):
        assert read_form_text_field({}, "answer_0") is None

    def test_read_multi_select_list(self):
        assert read_form_multi_select({"s": ["a", "b"]}, "s") == ["a", "b"]

    def test_read_multi_select_string(self):
        assert read_form_multi_select({"s": "a"}, "s") == ["a"]

    def test_read_multi_select_empty(self):
        assert read_form_multi_select({}, "s") == []

    def test_field_names(self):
        assert get_input_field_name(0) == "answer_0"
        assert get_select_field_name(2) == "selection_2"
