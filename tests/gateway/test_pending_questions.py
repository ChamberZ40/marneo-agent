# tests/gateway/test_pending_questions.py
"""Tests for PendingQuestionStore — async Future coordination layer."""
import asyncio
import time
from unittest.mock import patch

import pytest

from marneo.gateway.pending_questions import PendingQuestionStore


# ── Helpers ─────────────────────────────────────────────────────────────────

@pytest.fixture
def store() -> PendingQuestionStore:
    """Fresh store per test (not the module singleton)."""
    return PendingQuestionStore()


# ── test_create_returns_id_and_future ───────────────────────────────────────

@pytest.mark.asyncio
async def test_create_returns_id_and_future(store: PendingQuestionStore):
    """create() must return a (str, Future) tuple with an mq_ prefixed id."""
    loop = asyncio.get_running_loop()
    question_id, future = store.create(
        chat_id="chat_abc",
        question="Pick a colour?",
        choices=["red", "blue"],
        loop=loop,
    )
    assert isinstance(question_id, str)
    assert question_id.startswith("mq_")
    assert isinstance(future, asyncio.Future)
    assert not future.done()


# ── test_resolve_completes_future ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_completes_future(store: PendingQuestionStore):
    """resolve() sets the Future result so awaiting it yields the answer."""
    loop = asyncio.get_running_loop()
    qid, future = store.create(
        chat_id="chat_abc",
        question="Continue?",
        choices=["yes", "no"],
        loop=loop,
    )
    resolved = store.resolve(qid, "yes")
    assert resolved is True

    # Allow call_soon_threadsafe callback to execute
    await asyncio.sleep(0)
    assert future.done()
    assert future.result() == "yes"


# ── test_resolve_unknown_returns_false ──────────────────────────────────────

def test_resolve_unknown_returns_false(store: PendingQuestionStore):
    """resolve() with a non-existent question_id must return False."""
    assert store.resolve("mq_does_not_exist", "answer") is False


# ── test_resolve_twice_returns_false ────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_twice_returns_false(store: PendingQuestionStore):
    """Second resolve for the same question_id returns False (already popped)."""
    loop = asyncio.get_running_loop()
    qid, future = store.create(
        chat_id="chat_abc",
        question="Pick one?",
        choices=["A", "B"],
        loop=loop,
    )
    assert store.resolve(qid, "A") is True
    # Second resolve — question already removed from store
    assert store.resolve(qid, "B") is False


# ── test_cancel_expired ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_expired(store: PendingQuestionStore):
    """cancel_expired returns count of expired questions and resolves them."""
    loop = asyncio.get_running_loop()
    qid, future = store.create(
        chat_id="chat_abc",
        question="Timeout question?",
        choices=[],
        loop=loop,
    )

    # Artificially age the question by setting created_at in the past
    with store._lock:
        pq = store._pending[qid]
        pq.created_at = time.monotonic() - 600  # 10 minutes ago

    cancelled = store.cancel_expired(timeout=300)
    assert cancelled == 1

    # Future should be resolved with the timeout message
    await asyncio.sleep(0)
    assert future.done()
    assert future.result() == "用户未回复（超时）"


# ── test_cancel_expired_skips_fresh ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_expired_skips_fresh(store: PendingQuestionStore):
    """cancel_expired must not touch questions still within timeout."""
    loop = asyncio.get_running_loop()
    _, future = store.create(
        chat_id="chat_abc",
        question="Fresh question?",
        choices=[],
        loop=loop,
    )
    cancelled = store.cancel_expired(timeout=300)
    assert cancelled == 0
    assert not future.done()


# ── test_resolve_by_chat_text ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_by_chat_text(store: PendingQuestionStore):
    """resolve_by_chat_text resolves the oldest text-reply question for a chat."""
    loop = asyncio.get_running_loop()
    qid1, future1 = store.create(
        chat_id="chat_xyz",
        question="First question (text)?",
        choices=[],  # text reply
        loop=loop,
    )
    qid2, future2 = store.create(
        chat_id="chat_xyz",
        question="Second question (text)?",
        choices=[],  # text reply
        loop=loop,
    )

    resolved = store.resolve_by_chat_text("chat_xyz", "my answer")
    assert resolved is True

    await asyncio.sleep(0)
    # Should resolve the first (oldest) question
    assert future1.done()
    assert future1.result() == "my answer"
    # Second still pending
    assert not future2.done()


# ── test_resolve_by_chat_text_ignores_choice_questions ──────────────────────

@pytest.mark.asyncio
async def test_resolve_by_chat_text_ignores_choice_questions(store: PendingQuestionStore):
    """resolve_by_chat_text must skip questions that have choices (button-based)."""
    loop = asyncio.get_running_loop()
    _, future_btn = store.create(
        chat_id="chat_xyz",
        question="Button Q?",
        choices=["A", "B"],
        loop=loop,
    )
    resolved = store.resolve_by_chat_text("chat_xyz", "typed text")
    assert resolved is False
    assert not future_btn.done()


# ── test_has_pending_for_chat ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_has_pending_for_chat(store: PendingQuestionStore):
    """has_pending_for_chat returns True only for chats with text-reply Qs."""
    loop = asyncio.get_running_loop()
    store.create(chat_id="chat_a", question="Q?", choices=[], loop=loop)

    assert store.has_pending_for_chat("chat_a") is True
    assert store.has_pending_for_chat("chat_b") is False
