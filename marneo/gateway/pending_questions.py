# marneo/gateway/pending_questions.py
"""Pending question registry — faithful port of openclaw-lark ask-user-question.js.

Non-blocking pattern:
- store_pending_question(): register question context after card is sent
- consume_pending_question(): remove and return context (disarms TTL)
- find_question_by_chat(): chat-scoped fallback when operationId is missing
- arm_ttl_timer(): auto-expire after 5 min, update card to expired state

Key differences from old blocking-Future pattern:
- NO asyncio.Future — the tool returns immediately
- Answers arrive via synthetic message injection in a NEW conversation turn
- TTL fires a callback that updates the card to expired state
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PENDING_QUESTION_TTL_MS = 5 * 60 * 1000  # 5 minutes in ms
PENDING_QUESTION_TTL_S = PENDING_QUESTION_TTL_MS / 1000  # 300s

INJECT_MAX_RETRIES = 2
INJECT_RETRY_DELAY_S = 2.0

SUBMIT_BUTTON_PREFIX = "ask_user_submit_"

INPUT_FIELD_NAME = "answer"
SELECT_FIELD_NAME = "selection"

ACTION_SUBMIT = "ask_user_submit"


# ---------------------------------------------------------------------------
# Question context (replaces old PendingQuestion dataclass)
# ---------------------------------------------------------------------------


@dataclass
class PendingQuestionContext:
    """All state needed to process a user's form submission.

    Faithfully ports the JS `PendingQuestionCtx` type from openclaw.
    """
    question_id: str
    chat_id: str
    account_id: str  # maps to openclaw accountId (app_id in marneo)
    sender_open_id: str
    card_id: str
    questions: list[dict]  # full question objects [{question, header, options, multiSelect}]
    message_id: str  # original message that triggered the tool
    chat_type: str = "p2p"
    thread_id: str = ""
    card_sequence: int = 1
    submitted: bool = False

    # Runtime references (not serialized)
    adapter: Any = None  # FeishuChannelAdapter reference for card updates + dispatch
    ttl_timer: Optional[asyncio.TimerHandle] = None


# ---------------------------------------------------------------------------
# Field name helpers (match openclaw exactly)
# ---------------------------------------------------------------------------


def get_input_field_name(question_index: int) -> str:
    """Field name for free-text input: answer_0, answer_1, ..."""
    return f"{INPUT_FIELD_NAME}_{question_index}"


def get_select_field_name(question_index: int) -> str:
    """Field name for select/multi_select: selection_0, selection_1, ..."""
    return f"{SELECT_FIELD_NAME}_{question_index}"


# ---------------------------------------------------------------------------
# Pending Question Registry (module-level singletons)
# ---------------------------------------------------------------------------

_pending_questions: dict[str, PendingQuestionContext] = {}
_by_chat_context: dict[str, set[str]] = {}  # chatKey → Set[questionId]
_lock = threading.Lock()


def _build_chat_key(account_id: str, chat_id: str) -> str:
    """Build secondary index key: account_id:chat_id (mirrors openclaw buildQueueKey)."""
    return f"{account_id}:{chat_id}"


def arm_ttl_timer(ctx: PendingQuestionContext, delay_s: float = PENDING_QUESTION_TTL_S) -> None:
    """Arm (or re-arm) the TTL expiry timer for a pending question.

    On expiry: consume the question and update card to expired state (fire-and-forget).
    Uses the adapter's event loop for scheduling.
    """
    # Cancel previous timer
    if ctx.ttl_timer is not None:
        ctx.ttl_timer.cancel()
        ctx.ttl_timer = None

    adapter = ctx.adapter
    if adapter is None:
        return

    loop = getattr(adapter, "_loop", None)
    if loop is None or loop.is_closed():
        return

    def _on_expire() -> None:
        with _lock:
            if ctx.question_id not in _pending_questions:
                return  # already consumed
            if ctx.submitted:
                return  # user submitted, injection in progress

        log.info("[PendingQ] question %s expired (TTL %.0fs)", ctx.question_id, delay_s)
        consume_pending_question(ctx.question_id)

        # Update card to expired state (fire-and-forget)
        asyncio.ensure_future(_update_card_to_expired(ctx), loop=loop)

    try:
        ctx.ttl_timer = loop.call_later(delay_s, _on_expire)
    except RuntimeError:
        # Loop is closed or not running
        pass


async def _update_card_to_expired(ctx: PendingQuestionContext) -> None:
    """Update card to expired state after TTL. Fire-and-forget."""
    try:
        from marneo.tools.core.ask_user import build_expired_card, update_card
        expired_card = build_expired_card(ctx.questions)
        ctx.card_sequence += 1
        await update_card(ctx.adapter, ctx.card_id, expired_card, ctx.card_sequence)
    except Exception as exc:
        log.warning("[PendingQ] Failed to update card to expired state: %s", exc)


def store_pending_question(ctx: PendingQuestionContext) -> None:
    """Store a pending question and arm its TTL timer.

    Primary index: question_id → context
    Secondary index: account_id:chat_id → Set[question_id] (for fallback lookup)
    """
    with _lock:
        _pending_questions[ctx.question_id] = ctx

        chat_key = _build_chat_key(ctx.account_id, ctx.chat_id)
        if chat_key not in _by_chat_context:
            _by_chat_context[chat_key] = set()
        _by_chat_context[chat_key].add(ctx.question_id)

    arm_ttl_timer(ctx, PENDING_QUESTION_TTL_S)


def consume_pending_question(question_id: str) -> Optional[PendingQuestionContext]:
    """Remove and return a pending question. Disarms TTL timer.

    Returns the context if found, None if already consumed/expired.
    """
    with _lock:
        ctx = _pending_questions.pop(question_id, None)
        if ctx is not None:
            # Remove from secondary index
            chat_key = _build_chat_key(ctx.account_id, ctx.chat_id)
            s = _by_chat_context.get(chat_key)
            if s is not None:
                s.discard(question_id)
                if not s:
                    del _by_chat_context[chat_key]

    if ctx is not None:
        # Disarm TTL timer
        if ctx.ttl_timer is not None:
            ctx.ttl_timer.cancel()
            ctx.ttl_timer = None

    return ctx


def get_pending_question(question_id: str) -> Optional[PendingQuestionContext]:
    """Look up a pending question by ID without consuming it."""
    with _lock:
        return _pending_questions.get(question_id)


def pending_questions_snapshot(account_id: str = "") -> dict[str, Any]:
    """Return non-sensitive pending-question queue counters for health/debugging."""
    with _lock:
        pending = [
            ctx for ctx in _pending_questions.values()
            if not ctx.submitted and (not account_id or ctx.account_id == account_id)
        ]
        by_chat: dict[str, int] = {}
        for ctx in pending:
            key = _build_chat_key(ctx.account_id, ctx.chat_id)
            by_chat[key] = by_chat.get(key, 0) + 1
        return {
            "total": len(pending),
            "by_chat": dict(sorted(by_chat.items())),
        }


def find_question_by_chat(account_id: str, chat_id: str) -> Optional[PendingQuestionContext]:
    """Chat-scoped fallback: find the single non-submitted pending question for a chat.

    Only returns a result when exactly one non-submitted pending question
    exists for this chat. Refuses to guess when ambiguous (multiple pending).

    Used when operationId cannot be extracted from the card callback.
    """
    chat_key = _build_chat_key(account_id, chat_id)

    with _lock:
        qids = _by_chat_context.get(chat_key)
        if not qids:
            return None

        match: Optional[PendingQuestionContext] = None
        for qid in qids:
            ctx = _pending_questions.get(qid)
            if ctx is not None and not ctx.submitted:
                if match is not None:
                    # Ambiguous: more than one non-submitted question in this chat
                    log.warning(
                        "[PendingQ] Chat-scoped fallback ambiguous: multiple pending in %s",
                        chat_key,
                    )
                    return None
                match = ctx

    return match


# ---------------------------------------------------------------------------
# Form value readers (match openclaw exactly)
# ---------------------------------------------------------------------------


def read_form_text_field(form_value: dict, field_name: str) -> Optional[str]:
    """Read a text field from form_value. Returns trimmed string or None."""
    value = form_value.get(field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def read_form_multi_select(form_value: dict, field_name: str) -> list[str]:
    """Read a multi-select field from form_value. Returns list of selected values."""
    import json as _json

    raw = form_value.get(field_name)

    if isinstance(raw, list):
        return [v for v in raw if isinstance(v, str) and v.strip()]

    if isinstance(raw, str) and raw.strip():
        # Try JSON parse (some SDK versions serialize as JSON string)
        try:
            parsed = _json.loads(raw.strip())
            if isinstance(parsed, list):
                return [v for v in parsed if isinstance(v, str) and v.strip()]
        except (ValueError, TypeError):
            pass
        return [raw.strip()]

    return []


# ---------------------------------------------------------------------------
# Backward compat: old PendingQuestionStore (used by existing code)
# ---------------------------------------------------------------------------

class PendingQuestionStore:
    """Thin compatibility wrapper over the new module-level registry.

    The old code used pending_question_store.create() / .resolve() with
    asyncio.Future. New code uses store_pending_question() / consume_pending_question()
    directly. This wrapper exists to keep older Feishu adapter call-sites working
    while preserving the new non-blocking pattern: answers are injected as a
    synthetic chat message in a new turn.
    """

    def has_pending_for_chat(self, chat_id: str) -> bool:
        """Check if there are any pending questions for a chat (any account)."""
        with _lock:
            for ctx in _pending_questions.values():
                if ctx.chat_id == chat_id and not ctx.submitted:
                    return True
        return False

    def resolve(self, question_id: str, answer: str | dict[str, str]) -> bool:
        """Consume a question by id and inject its answer as synthetic text.

        `answer` may be the legacy single-answer string or a dict keyed by the
        original question text. Returns False when the question was expired or
        already consumed.
        """
        ctx = consume_pending_question(question_id)
        if ctx is None:
            return False
        answers = _normalise_answers(ctx, answer)
        _schedule_answer_injection(ctx, answers)
        return True

    def resolve_by_chat_text(self, chat_id: str, raw_text: str) -> bool:
        """Resolve the single pending question in a chat using a plain text reply."""
        match: Optional[PendingQuestionContext] = None
        with _lock:
            for ctx in _pending_questions.values():
                if ctx.chat_id != chat_id or ctx.submitted:
                    continue
                if match is not None:
                    log.warning("[PendingQ] Text reply fallback ambiguous: multiple pending in chat %s", chat_id)
                    return False
                match = ctx
        if match is None:
            return False
        ctx = consume_pending_question(match.question_id)
        if ctx is None:
            return False
        answers = _normalise_answers(ctx, raw_text)
        _schedule_answer_injection(ctx, answers)
        return True


def _normalise_answers(ctx: PendingQuestionContext, answer: str | dict[str, str]) -> dict[str, str]:
    """Build question-text → answer mapping for card updates and synthetic text."""
    if isinstance(answer, dict):
        return {str(k): str(v) for k, v in answer.items()}

    questions = ctx.questions or []
    if not questions:
        return {"回答": str(answer)}

    # Legacy single-answer path: attach the text to the first question and mark
    # the rest as unanswered instead of losing question context.
    result: dict[str, str] = {}
    for i, q in enumerate(questions):
        question_text = str(q.get("question") or q.get("header") or f"问题 {i + 1}")
        result[question_text] = str(answer) if i == 0 else "(no answer)"
    return result


def _format_answer_message(ctx: PendingQuestionContext, answers: dict[str, str]) -> str:
    lines = ["用户已回答上一轮 ask_user 问题："]
    for i, q in enumerate(ctx.questions or []):
        question_text = str(q.get("question") or q.get("header") or f"问题 {i + 1}")
        lines.append(f"- {question_text}: {answers.get(question_text, '(no answer)')}")
    if not ctx.questions:
        for key, value in answers.items():
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _schedule_answer_injection(ctx: PendingQuestionContext, answers: dict[str, str]) -> None:
    """Fire-and-forget card update + synthetic dispatch on the adapter loop."""
    ctx.submitted = True
    adapter = ctx.adapter
    loop = getattr(adapter, "_loop", None) if adapter is not None else None
    if adapter is None or loop is None or loop.is_closed():
        log.warning("[PendingQ] Cannot inject answer for %s: adapter loop unavailable", ctx.question_id)
        return

    async def _inject() -> None:
        try:
            from marneo.gateway.base import ChannelMessage
            from marneo.tools.core.ask_user import build_answered_card, build_processing_card, update_card

            if ctx.card_id:
                try:
                    ctx.card_sequence += 1
                    await update_card(adapter, ctx.card_id, build_processing_card(ctx.questions, answers), ctx.card_sequence)
                except Exception as exc:
                    log.debug("[PendingQ] Processing card update failed: %s", exc)

            channel_msg = ChannelMessage(
                platform=getattr(adapter, "platform", "feishu"),
                chat_id=ctx.chat_id,
                user_id=ctx.sender_open_id,
                chat_type=ctx.chat_type or "p2p",
                text=_format_answer_message(ctx, answers),
                msg_id=f"ask_user:{ctx.question_id}",
                context_token=ctx.thread_id or "",
            )
            await adapter._manager.dispatch(channel_msg)

            if ctx.card_id:
                try:
                    ctx.card_sequence += 1
                    await update_card(adapter, ctx.card_id, build_answered_card(ctx.questions, answers), ctx.card_sequence)
                except Exception as exc:
                    log.debug("[PendingQ] Answered card update failed: %s", exc)
        except Exception as exc:
            log.warning("[PendingQ] Failed to inject answer for %s: %s", ctx.question_id, exc)

    try:
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_inject(), loop)
        else:
            loop.create_task(_inject())
    except RuntimeError as exc:
        log.warning("[PendingQ] Cannot schedule answer injection for %s: %s", ctx.question_id, exc)


# Module-level singleton for backward compat
pending_question_store = PendingQuestionStore()
