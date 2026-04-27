# marneo/tools/core/ask_user.py
"""ask_user tool — send interactive Feishu card and wait for user response.

Ported from hermes-agent's clarify tool pattern. Enables the LLM to ask
the user a question (with optional button choices) and block until the
user responds.

Flow:
  1. LLM calls ask_user with question + optional choices
  2. Tool sends interactive card to chat via Feishu API
  3. Tool blocks on asyncio.Future waiting for user response
  4. User clicks button -> card.action.trigger callback resolves Future
  5. Tool returns the user's answer to the agentic loop
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from marneo.tools.registry import registry, tool_result, tool_error

log = logging.getLogger(__name__)

_ASK_USER_TIMEOUT = 300  # 5 minutes default

# ── Context variable for chat context ────────────────────────────────────────
# Set by the gateway adapter before the agentic loop runs, so the ask_user
# tool can access chat_id and send_card_fn without modifying the engine.


@dataclass
class AskUserContext:
    """Runtime context for ask_user tool, set per-request by the adapter."""
    chat_id: str
    adapter: Any  # FeishuChannelAdapter — used for credentials and sending cards


# Context variable — set in feishu.py before process_streaming / _process
ask_user_ctx: contextvars.ContextVar[Optional[AskUserContext]] = contextvars.ContextVar(
    "ask_user_ctx", default=None
)


# ── Card sending ─────────────────────────────────────────────────────────────


async def _send_ask_card(
    adapter: Any,
    chat_id: str,
    question: str,
    question_id: str,
    choices: list[str],
) -> bool:
    """Send the interactive ask_user card to the chat. Returns True on success."""
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        lark_domain = lark.LARK_DOMAIN if adapter._domain == "lark" else lark.FEISHU_DOMAIN
        client = (
            lark.Client.builder()
            .app_id(adapter._app_id)
            .app_secret(adapter._app_secret)
            .domain(lark_domain)
            .build()
        )

        # Build card content
        elements: list[dict] = [
            {"tag": "markdown", "content": f"**{question}**"},
        ]

        if choices:
            buttons: list[dict] = []
            for i, choice in enumerate(choices):
                btn_type = "primary" if i == 0 else "default"
                buttons.append({
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": choice},
                    "type": btn_type,
                    "value": {
                        "marneo_question_id": question_id,
                        "answer": choice,
                    },
                })
            elements.append({"tag": "action", "actions": buttons})
        else:
            elements.append({
                "tag": "markdown",
                "content": "_请直接回复文字消息_",
            })

        card_content = json.dumps({
            "elements": elements,
        }, ensure_ascii=False)

        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(card_content)
            .build()
        )
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        resp = await asyncio.to_thread(client.im.v1.message.create, request)

        if resp and getattr(resp, "success", lambda: False)():
            log.info("[ask_user] Card sent to chat %s (question_id=%s)",
                     chat_id[:12] if chat_id else "?", question_id)
            return True

        log.warning("[ask_user] Card send failed: code=%s msg=%s",
                    getattr(resp, "code", "?"), getattr(resp, "msg", "?"))
        return False

    except Exception as exc:
        log.error("[ask_user] Card send error: %s", exc, exc_info=True)
        return False


# ── Tool handler ─────────────────────────────────────────────────────────────

async def ask_user_handler(args: dict[str, Any], **kw: Any) -> str:
    """Send a question to the user and wait for their response."""
    question = args.get("question", "").strip()
    choices = args.get("choices", []) or []

    if not question:
        return tool_error("question is required")

    # Validate choices
    if not isinstance(choices, list):
        choices = []
    choices = [str(c).strip() for c in choices if str(c).strip()]
    if len(choices) > 4:
        choices = choices[:4]

    # Get context
    ctx = ask_user_ctx.get()
    if ctx is None:
        return tool_error(
            "ask_user is only available in Feishu chat context. "
            "No active chat context found."
        )

    chat_id = ctx.chat_id
    adapter = ctx.adapter
    if not chat_id or not adapter:
        return tool_error("Missing chat_id or adapter in ask_user context")

    # Import pending question store
    from marneo.gateway.pending_questions import pending_question_store

    # Get the running event loop
    loop = asyncio.get_running_loop()

    # Create pending question
    question_id, future = pending_question_store.create(
        chat_id=chat_id,
        question=question,
        choices=choices,
        loop=loop,
    )

    # Send the interactive card
    sent = await _send_ask_card(adapter, chat_id, question, question_id, choices)
    if not sent:
        # Clean up the pending question
        pending_question_store.resolve(question_id, "")
        return tool_error("Failed to send question card to Feishu")

    # Wait for user response with timeout
    try:
        answer = await asyncio.wait_for(future, timeout=_ASK_USER_TIMEOUT)
        return tool_result(answer=answer, question=question, question_id=question_id)
    except asyncio.TimeoutError:
        # Clean up expired question
        pending_question_store.cancel_expired(timeout=0)
        return tool_result(
            answer="用户未回复（超时）",
            question=question,
            question_id=question_id,
            timed_out=True,
        )


# ── Registration ─────────────────────────────────────────────────────────────

registry.register(
    name="ask_user",
    description=(
        "Send a question to the user with optional choices and wait for their response. "
        "Use when you need clarification or approval before proceeding."
    ),
    schema={
        "name": "ask_user",
        "description": (
            "Send a question to the user with optional choices and wait for their response. "
            "Use when you need clarification, confirmation, or the user to choose between options. "
            "If choices are provided, an interactive card with buttons is sent. "
            "If no choices are provided, the user replies via text message. "
            "Returns the user's answer as a string."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user",
                },
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 4,
                    "description": (
                        "Optional button choices (max 4). "
                        "If empty or omitted, waits for free-text reply."
                    ),
                },
            },
            "required": ["question"],
        },
    },
    handler=ask_user_handler,
    is_async=True,
    emoji="",
)
