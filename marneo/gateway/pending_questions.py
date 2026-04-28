# marneo/gateway/pending_questions.py
"""Pending question store for ask_user tool <-> card callback coordination.

Thread-safe store that bridges the async agentic loop (ask_user tool creates
a pending question and waits on a Future) with the WS callback thread
(card action resolves the Future with the user's answer).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from typing import Any, Optional

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 300  # 5 minutes


class PendingQuestion:
    """A question awaiting user response."""

    __slots__ = ("question_id", "chat_id", "question", "choices", "future", "created_at", "loop", "questions_data")

    def __init__(
        self,
        question_id: str,
        chat_id: str,
        question: str,
        choices: list[str],
        future: asyncio.Future,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.question_id = question_id
        self.chat_id = chat_id
        self.question = question
        self.choices = choices
        self.future = future
        self.loop = loop
        self.created_at = time.monotonic()
        self.questions_data: list[dict] = []  # full question objects for form parsing


class PendingQuestionStore:
    """Thread-safe store for questions awaiting user response.

    Accessed from:
    - Async main loop (ask_user tool creates questions)
    - WS callback thread (card action resolves questions)
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingQuestion] = {}
        self._lock = threading.Lock()

    def create(
        self,
        chat_id: str,
        question: str,
        choices: list[str],
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[str, asyncio.Future]:
        """Create a pending question. Returns (question_id, future).

        The future is created on the provided event loop so it can be
        resolved from the WS callback thread via call_soon_threadsafe.
        """
        question_id = f"mq_{uuid.uuid4().hex[:12]}"
        future = loop.create_future()

        pq = PendingQuestion(
            question_id=question_id,
            chat_id=chat_id,
            question=question,
            choices=choices,
            future=future,
            loop=loop,
        )

        with self._lock:
            self._pending[question_id] = pq

        log.info("[PendingQ] Created %s for chat %s: %s",
                 question_id, chat_id[:12] if chat_id else "?", question[:60])
        return question_id, future

    def set_questions(self, question_id: str, questions: list[dict]) -> None:
        """Store full question objects for form answer parsing."""
        with self._lock:
            pq = self._pending.get(question_id)
            if pq:
                pq.questions_data = questions

    def get_questions(self, question_id: str) -> list[dict]:
        """Get stored question objects for a pending question."""
        with self._lock:
            pq = self._pending.get(question_id)
            return pq.questions_data if pq else []

    def resolve(self, question_id: str, answer: str) -> bool:
        """Resolve a pending question with user's answer.

        Called from WS callback thread. Uses call_soon_threadsafe to set
        the future result on the correct event loop.

        Returns True if the question was found and resolved.
        """
        with self._lock:
            pq = self._pending.pop(question_id, None)

        if pq is None:
            log.debug("[PendingQ] Question %s not found (expired or already resolved)", question_id)
            return False

        if pq.future.done():
            log.debug("[PendingQ] Question %s already done", question_id)
            return False

        # Thread-safe: set result on the event loop that owns the future
        pq.loop.call_soon_threadsafe(pq.future.set_result, answer)
        log.info("[PendingQ] Resolved %s with answer: %s", question_id, answer[:60])
        return True

    def resolve_by_chat_text(self, chat_id: str, text: str) -> bool:
        """Resolve the oldest pending question for a chat with free-text reply.

        Used when ask_user has no choices (user replies via text message).
        Returns True if a question was resolved.
        """
        with self._lock:
            # Find oldest pending question for this chat
            target_id: Optional[str] = None
            target_pq: Optional[PendingQuestion] = None
            for qid, pq in self._pending.items():
                if pq.chat_id == chat_id and not pq.choices and not pq.future.done():
                    if target_pq is None or pq.created_at < target_pq.created_at:
                        target_id = qid
                        target_pq = pq

            if target_id is not None:
                del self._pending[target_id]

        if target_pq is None:
            return False

        if target_pq.future.done():
            return False

        target_pq.loop.call_soon_threadsafe(target_pq.future.set_result, text)
        log.info("[PendingQ] Resolved %s (text reply) for chat %s",
                 target_id, chat_id[:12] if chat_id else "?")
        return True

    def has_pending_for_chat(self, chat_id: str) -> bool:
        """Check if there are any pending text-reply questions for a chat."""
        with self._lock:
            return any(
                pq.chat_id == chat_id and not pq.choices and not pq.future.done()
                for pq in self._pending.values()
            )

    def cancel_expired(self, timeout: float = _DEFAULT_TIMEOUT) -> int:
        """Cancel questions that exceeded timeout. Returns count cancelled."""
        now = time.monotonic()
        expired: list[PendingQuestion] = []

        with self._lock:
            expired_ids = [
                qid for qid, pq in self._pending.items()
                if now - pq.created_at > timeout
            ]
            for qid in expired_ids:
                expired.append(self._pending.pop(qid))

        for pq in expired:
            if not pq.future.done():
                pq.loop.call_soon_threadsafe(
                    pq.future.set_result, "用户未回复（超时）"
                )

        if expired:
            log.info("[PendingQ] Cancelled %d expired questions", len(expired))
        return len(expired)


# Module-level singleton
pending_question_store = PendingQuestionStore()
