# marneo/tools/core/ask_user.py
"""ask_user tool — send interactive Feishu card and wait for user response.

Ported from openclaw-lark's ask-user-question.ts pattern:
- Form container with select_static dropdowns (not independent buttons)
- Left-right layout (column_set) for label + control
- Option descriptions below each dropdown
- Card header with title + status tag + question count
- Single "提交" submit button at bottom
- Supports 1-6 questions per card
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
_SUBMIT_BUTTON_PREFIX = "ask_user_submit_"

# ── Context variable for chat context ────────────────────────────────────────


@dataclass
class AskUserContext:
    """Runtime context for ask_user tool, set per-request by the adapter."""
    chat_id: str
    adapter: Any


ask_user_ctx: contextvars.ContextVar[Optional[AskUserContext]] = contextvars.ContextVar(
    "ask_user_ctx", default=None
)


# ── Card builder (openclaw form pattern) ─────────────────────────────────────


def _build_labeled_row(label_md: str, control: dict) -> dict:
    """Build a left-right row: label on left, control on right (openclaw pattern)."""
    return {
        "tag": "column_set",
        "flex_mode": "stretch",
        "horizontal_spacing": "8px",
        "margin": "12px 0 0 0",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "vertical_align": "center",
                "elements": [{"tag": "markdown", "content": f"**{label_md}**"}],
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 3,
                "vertical_align": "center",
                "elements": [control],
            },
        ],
    }


def _build_question_elements(q: dict, index: int) -> list[dict]:
    """Build form elements for a single question (openclaw pattern)."""
    elems: list[dict] = []
    question_text = q.get("question", "")
    header = q.get("header", f"问题 {index + 1}")
    options = q.get("options", [])
    multi_select = q.get("multiSelect", False)

    # Question description
    if question_text and question_text != header:
        elems.append({"tag": "markdown", "content": question_text, "text_size": "notation"})

    if not options:
        # Free-text input
        elems.append(_build_labeled_row(header, {
            "tag": "input",
            "name": f"answer_{index}",
            "placeholder": {"tag": "plain_text", "content": "请输入..."},
        }))
        return elems

    # Build select options
    select_options = [
        {"text": {"tag": "plain_text", "content": opt.get("label", str(opt))},
         "value": opt.get("label", str(opt))}
        for opt in options
    ]

    if multi_select:
        control = {
            "tag": "multi_select_static",
            "name": f"selection_{index}",
            "placeholder": {"tag": "plain_text", "content": "请选择..."},
            "options": select_options,
        }
    else:
        control = {
            "tag": "select_static",
            "name": f"selection_{index}",
            "placeholder": {"tag": "plain_text", "content": "请选择..."},
            "options": select_options,
        }

    elems.append(_build_labeled_row(header, control))

    # Option descriptions
    desc_lines = [
        f"· **{opt.get('label', '')}**: {opt.get('description', '')}"
        for opt in options if opt.get("description")
    ]
    if desc_lines:
        elems.append({"tag": "markdown", "content": "\n".join(desc_lines), "text_size": "notation"})

    return elems


def _build_ask_card(questions: list[dict], question_id: str) -> dict:
    """Build the full interactive ask-user card (openclaw Card Kit v2 pattern)."""
    form_elements: list[dict] = []
    for i, q in enumerate(questions):
        if i > 0:
            form_elements.append({"tag": "hr"})
        form_elements.extend(_build_question_elements(q, i))

    # Submit button
    form_elements.append({"tag": "hr"})
    form_elements.append({
        "tag": "button",
        "name": f"{_SUBMIT_BUTTON_PREFIX}{question_id}",
        "text": {"tag": "plain_text", "content": "📮 提交"},
        "type": "primary",
        "form_action_type": "submit",
    })

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "需要你的确认"},
            "subtitle": {
                "tag": "plain_text",
                "content": f"共 {len(questions)} 个问题",
            },
            "text_tag_list": [{
                "tag": "text_tag",
                "text": {"tag": "plain_text", "content": "待回答"},
                "color": "blue",
            }],
            "template": "blue",
        },
        "body": {
            "elements": [{
                "tag": "form",
                "name": "ask_user_form",
                "elements": form_elements,
            }],
        },
    }


def _build_answered_card(questions: list[dict], answers: dict) -> dict:
    """Build the answered state card (green header, show answers)."""
    elements: list[dict] = []
    for i, q in enumerate(questions):
        header = q.get("header", f"问题 {i + 1}")
        answer = answers.get(q.get("question", ""), "(未回答)")
        if i > 0:
            elements.append({"tag": "hr"})
        elements.append(_build_labeled_row(header, {
            "tag": "markdown", "content": f"✅ **{answer}**"
        }))

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "已收到回答"},
            "subtitle": {
                "tag": "plain_text",
                "content": f"共 {len(questions)} 个问题",
            },
            "text_tag_list": [{
                "tag": "text_tag",
                "text": {"tag": "plain_text", "content": "已完成"},
                "color": "green",
            }],
            "template": "green",
        },
        "body": {"elements": elements},
    }


# ── Card sending ─────────────────────────────────────────────────────────────


async def _send_ask_card(
    adapter: Any,
    chat_id: str,
    questions: list[dict],
    question_id: str,
) -> bool:
    """Create Card Kit entity and send as interactive message. Returns True on success."""
    try:
        import httpx

        base_url = (
            "https://open.larksuite.com/open-apis"
            if adapter._domain == "lark"
            else "https://open.feishu.cn/open-apis"
        )

        # Get token
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{base_url}/auth/v3/tenant_access_token/internal",
                json={"app_id": adapter._app_id, "app_secret": adapter._app_secret},
            )
            token = r.json().get("tenant_access_token", "")
            if not token:
                log.warning("[ask_user] Token fetch failed")
                return False

            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

            # 1. Create card entity via Card Kit
            card = _build_ask_card(questions, question_id)
            card_payload = json.dumps({
                "type": "card_json",
                "data": json.dumps(card, ensure_ascii=False),
            }, ensure_ascii=False)

            r2 = await client.post(
                f"{base_url}/cardkit/v1/cards",
                headers=headers,
                content=card_payload.encode(),
            )
            card_data = r2.json()
            if card_data.get("code") != 0:
                log.warning("[ask_user] Card creation failed: %s", card_data.get("msg"))
                return False
            card_id = card_data.get("data", {}).get("card_id")
            if not card_id:
                return False

            # 2. Send card as interactive message
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest, CreateMessageRequestBody,
            )
            lark_domain = lark.LARK_DOMAIN if adapter._domain == "lark" else lark.FEISHU_DOMAIN
            lark_client = (
                lark.Client.builder()
                .app_id(adapter._app_id)
                .app_secret(adapter._app_secret)
                .domain(lark_domain)
                .build()
            )
            card_content = json.dumps(
                {"type": "card", "data": {"card_id": card_id}}, ensure_ascii=False
            )
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
            resp = await asyncio.to_thread(lark_client.im.v1.message.create, request)

            if resp and getattr(resp, "success", lambda: False)():
                log.info("[ask_user] Card sent to chat %s (question_id=%s, card_id=%s)",
                         chat_id[:12], question_id, card_id)
                return True

            log.warning("[ask_user] Card send failed: code=%s", getattr(resp, "code", "?"))
            return False

    except Exception as exc:
        log.error("[ask_user] Card send error: %s", exc, exc_info=True)
        return False


# ── Tool handler ─────────────────────────────────────────────────────────────


async def ask_user_handler(args: dict[str, Any], **kw: Any) -> str:
    """Send questions to the user and wait for their response."""
    # Support both single-question and multi-question format
    questions_raw = args.get("questions", [])

    # Backward compat: single question + choices → convert to questions format
    if not questions_raw and args.get("question"):
        q = args["question"].strip()
        if not q:
            return tool_error("question is required")
        choices = args.get("choices", []) or []
        if not isinstance(choices, list):
            choices = []
        choices = [str(c).strip() for c in choices if str(c).strip()]
        questions_raw = [{
            "question": q,
            "header": q[:12],
            "options": [{"label": c, "description": ""} for c in choices[:4]],
            "multiSelect": False,
        }]

    if not questions_raw:
        return tool_error("questions is required (list of question objects)")

    # Validate and normalize
    questions: list[dict] = []
    for q in questions_raw[:6]:  # max 6 questions
        if isinstance(q, str):
            q = {"question": q, "header": q[:12], "options": [], "multiSelect": False}
        if not isinstance(q, dict):
            continue
        questions.append({
            "question": q.get("question", ""),
            "header": q.get("header", q.get("question", "")[:12]),
            "options": q.get("options", [])[:10],
            "multiSelect": bool(q.get("multiSelect", False)),
        })

    if not questions:
        return tool_error("No valid questions provided")

    # Get context
    ctx = ask_user_ctx.get()
    if ctx is None:
        return tool_error("ask_user is only available in Feishu chat context.")

    chat_id = ctx.chat_id
    adapter = ctx.adapter
    if not chat_id or not adapter:
        return tool_error("Missing chat_id or adapter in ask_user context")

    from marneo.gateway.pending_questions import pending_question_store

    loop = asyncio.get_running_loop()
    question_id, future = pending_question_store.create(
        chat_id=chat_id,
        question=questions[0].get("question", ""),
        choices=[],  # form-based, not button-based
        loop=loop,
    )

    # Store questions for answer parsing in callback
    pending_question_store.set_questions(question_id, questions)

    # Send the form card
    sent = await _send_ask_card(adapter, chat_id, questions, question_id)
    if not sent:
        pending_question_store.resolve(question_id, "")
        return tool_error("Failed to send question card to Feishu")

    # Wait for user response
    try:
        answer = await asyncio.wait_for(future, timeout=_ASK_USER_TIMEOUT)
        return tool_result(answer=answer, question_id=question_id)
    except asyncio.TimeoutError:
        pending_question_store.cancel_expired(timeout=0)
        return tool_result(answer="用户未回复（超时）", question_id=question_id, timed_out=True)


# ── Registration ─────────────────────────────────────────────────────────────

registry.register(
    name="ask_user",
    description=(
        "Send questions to the user with interactive form card and wait for response. "
        "Supports dropdown selection, multi-select, and free-text input."
    ),
    schema={
        "name": "ask_user",
        "description": (
            "Send questions to the user via an interactive Feishu form card. "
            "Supports 1-6 questions per card, each with dropdown options or free-text input. "
            "Returns the user's answers after they submit the form."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "The question to ask"},
                            "header": {"type": "string", "description": "Short label (max 12 chars)"},
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                    "required": ["label", "description"],
                                },
                                "maxItems": 10,
                                "description": "Choices as dropdown. Empty [] for free-text input.",
                            },
                            "multiSelect": {"type": "boolean", "description": "Allow multiple selections"},
                        },
                        "required": ["question", "header", "options", "multiSelect"],
                    },
                    "minItems": 1,
                    "maxItems": 6,
                },
                # Backward compat
                "question": {"type": "string", "description": "Single question (legacy format)"},
                "choices": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            },
        },
    },
    handler=ask_user_handler,
    is_async=True,
    emoji="",
)
