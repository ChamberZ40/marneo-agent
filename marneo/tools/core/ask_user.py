# marneo/tools/core/ask_user.py
"""ask_user tool — faithful port of openclaw-lark ask-user-question.js.

Non-blocking pattern (openclaw synthetic message architecture):
1. AI calls ask_user tool with questions array
2. Tool sends interactive form card via Card Kit v2
3. execute() returns IMMEDIATELY with {status: 'pending', questionId}
4. User fills form and submits — form_value arrives in card action callback
5. Callback handler parses answers, injects synthetic ChannelMessage via dispatch()
6. AI receives answers in a NEW conversation turn

Card state transitions (4 states, updated via Card Kit PATCH API):
- buildAskUserCard   → interactive form   (待回答, blue header)
- buildProcessingCard → submitted answers  (处理中, turquoise header)
- buildAnsweredCard   → final answers      (已完成, green header)
- buildExpiredCard    → expired            (已过期, grey header)
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from marneo.tools.registry import registry, tool_result, tool_error

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUBMIT_BUTTON_PREFIX = "ask_user_submit_"

# Shared V2 card config (matches openclaw exactly)
_V2_CONFIG: dict[str, Any] = {
    "wide_screen_mode": True,
    "update_multi": True,
    "locales": ["zh_cn", "en_us"],
}


# ---------------------------------------------------------------------------
# Context variable for chat context (kept for adapter → tool communication)
# ---------------------------------------------------------------------------


@dataclass
class AskUserContext:
    """Runtime context for ask_user tool, set per-request by the adapter."""
    chat_id: str
    adapter: Any
    sender_open_id: str = ""
    msg_id: str = ""
    chat_type: str = "p2p"
    thread_id: str = ""


ask_user_ctx: contextvars.ContextVar[Optional[AskUserContext]] = contextvars.ContextVar(
    "ask_user_ctx", default=None
)


# ---------------------------------------------------------------------------
# Card builders — unified form layout (faithful port of openclaw)
# ---------------------------------------------------------------------------


def _build_labeled_row(label: dict, control: dict) -> dict:
    """Build a left-right row: label on left (weight 1), control on right (weight 3).

    Matches openclaw buildLabeledRow() exactly.
    """
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
                "elements": [label],
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


def _build_question_form_elements(q: dict, question_index: int) -> list[dict]:
    """Build form elements for a single question.

    All controls use `name` for form_value collection. No `value` property
    is set on interactive components — they do not fire individual callbacks.

    Matches openclaw buildQuestionFormElements() exactly.
    """
    from marneo.gateway.pending_questions import get_input_field_name, get_select_field_name

    elems: list[dict] = []
    header = q.get("header", f"问题 {question_index + 1}")
    question_text = q.get("question", "")
    options = q.get("options", [])
    multi_select = q.get("multiSelect", False)

    label_md: dict = {"tag": "markdown", "content": f"**{header}**"}

    # Question description as subtitle
    if question_text and question_text != header:
        elems.append({"tag": "markdown", "content": question_text, "text_size": "notation"})

    if not options:
        # ---- Free-text input ----
        elems.append(_build_labeled_row(label_md, {
            "tag": "input",
            "name": get_input_field_name(question_index),
            "placeholder": {
                "tag": "plain_text",
                "content": "请输入...",
                "i18n_content": {"zh_cn": "请输入...", "en_us": "Type your answer..."},
            },
        }))
        return elems

    # ---- Build option list ----
    select_options = [
        {
            "text": {"tag": "plain_text", "content": opt.get("label", str(opt))},
            "value": opt.get("label", str(opt)),
        }
        for opt in options
    ]

    if multi_select:
        # ---- Multi-select dropdown ----
        elems.append(_build_labeled_row(label_md, {
            "tag": "multi_select_static",
            "name": get_select_field_name(question_index),
            "placeholder": {
                "tag": "plain_text",
                "content": "请选择...",
                "i18n_content": {"zh_cn": "请选择...", "en_us": "Select options..."},
            },
            "options": select_options,
        }))
    else:
        # ---- Single-select dropdown ----
        elems.append(_build_labeled_row(label_md, {
            "tag": "select_static",
            "name": get_select_field_name(question_index),
            "placeholder": {
                "tag": "plain_text",
                "content": "请选择...",
                "i18n_content": {"zh_cn": "请选择...", "en_us": "Select an option..."},
            },
            "options": select_options,
        }))

    # ---- Option descriptions ----
    desc_lines = [
        f"\u2022 **{opt.get('label', '')}**: {opt.get('description', '')}"
        for opt in options
        if opt.get("description")
    ]
    if desc_lines:
        elems.append({"tag": "markdown", "content": "\n".join(desc_lines), "text_size": "notation"})

    return elems


def build_ask_user_card(questions: list[dict], question_id: str) -> dict:
    """Build the full interactive ask-user card.

    All elements are wrapped in a single `form` container.
    Submit button uses `form_action_type: "submit"` to collect all values.

    Matches openclaw buildAskUserCard() exactly.
    """
    form_elements: list[dict] = []
    for i, q in enumerate(questions):
        if i > 0:
            form_elements.append({"tag": "hr"})
        form_elements.extend(_build_question_form_elements(q, i))

    # Submit button
    form_elements.append({"tag": "hr"})
    form_elements.append({
        "tag": "button",
        # Encode questionId in button name — value does NOT propagate for form submit buttons
        "name": f"{_SUBMIT_BUTTON_PREFIX}{question_id}",
        "text": {
            "tag": "plain_text",
            "content": "\U0001f4ee 提交",
            "i18n_content": {"zh_cn": "\U0001f4ee 提交", "en_us": "\U0001f4ee Submit"},
        },
        "type": "primary",
        "form_action_type": "submit",
    })

    count = len(questions)
    return {
        "schema": "2.0",
        "config": _V2_CONFIG,
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "需要你的确认",
                "i18n_content": {"zh_cn": "需要你的确认", "en_us": "Your Input Needed"},
            },
            "subtitle": {
                "tag": "plain_text",
                "content": f"共 {count} 个问题",
                "i18n_content": {
                    "zh_cn": f"共 {count} 个问题",
                    "en_us": f"{count} question{'s' if count > 1 else ''}",
                },
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


def build_processing_card(questions: list[dict], answers: dict[str, str]) -> dict:
    """Build the processing state card (turquoise header, answers with hourglass).

    Matches openclaw buildProcessingCard() exactly.
    """
    elements: list[dict] = []
    for i, q in enumerate(questions):
        question_text = q.get("question", "")
        answer = answers.get(question_text, "(no answer)")
        header = q.get("header", f"问题 {i + 1}")
        if i > 0:
            elements.append({"tag": "hr"})
        elements.append(_build_labeled_row(
            {"tag": "markdown", "content": f"**{header}**"},
            {"tag": "markdown", "content": f"\u23f3 **{answer}**"},
        ))

    elements.append({
        "tag": "markdown",
        "content": "正在处理你的回答...",
        "text_size": "notation",
    })

    count = len(questions)
    return {
        "schema": "2.0",
        "config": _V2_CONFIG,
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "已提交回答",
                "i18n_content": {"zh_cn": "已提交回答", "en_us": "Response Submitted"},
            },
            "subtitle": {
                "tag": "plain_text",
                "content": f"共 {count} 个问题 \u00b7 正在处理",
                "i18n_content": {
                    "zh_cn": f"共 {count} 个问题 \u00b7 正在处理",
                    "en_us": f"{count} question{'s' if count > 1 else ''} \u00b7 Processing",
                },
            },
            "text_tag_list": [{
                "tag": "text_tag",
                "text": {"tag": "plain_text", "content": "处理中"},
                "color": "turquoise",
            }],
            "template": "turquoise",
        },
        "body": {"elements": elements},
    }


def build_answered_card(questions: list[dict], answers: dict[str, str]) -> dict:
    """Build the answered state card (green header, answers with checkmark).

    Matches openclaw buildAnsweredCard() exactly.
    """
    elements: list[dict] = []
    for i, q in enumerate(questions):
        question_text = q.get("question", "")
        answer = answers.get(question_text, "(no answer)")
        header = q.get("header", f"问题 {i + 1}")
        if i > 0:
            elements.append({"tag": "hr"})
        elements.append(_build_labeled_row(
            {"tag": "markdown", "content": f"**{header}**"},
            {"tag": "markdown", "content": f"\u2705 **{answer}**"},
        ))

    count = len(questions)
    return {
        "schema": "2.0",
        "config": _V2_CONFIG,
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "已收到回答",
                "i18n_content": {"zh_cn": "已收到回答", "en_us": "Response Received"},
            },
            "subtitle": {
                "tag": "plain_text",
                "content": f"共 {count} 个问题",
                "i18n_content": {
                    "zh_cn": f"共 {count} 个问题",
                    "en_us": f"{count} question{'s' if count > 1 else ''}",
                },
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


def build_expired_card(questions: list[dict]) -> dict:
    """Build the expired state card (grey header).

    Matches openclaw buildExpiredCard() exactly.
    """
    elements: list[dict] = []
    for i, q in enumerate(questions):
        header = q.get("header", f"问题 {i + 1}")
        question_text = q.get("question", "")
        if i > 0:
            elements.append({"tag": "hr"})
        elements.append(_build_labeled_row(
            {"tag": "markdown", "content": f"**{header}**"},
            {"tag": "markdown", "content": question_text},
        ))

    elements.append({
        "tag": "markdown",
        "content": "\u23f1 该问题已过期",
        "i18n_content": {"zh_cn": "\u23f1 该问题已过期", "en_us": "\u23f1 This question has expired"},
        "text_size": "notation",
    })

    return {
        "schema": "2.0",
        "config": _V2_CONFIG,
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "问题已过期",
                "i18n_content": {"zh_cn": "问题已过期", "en_us": "Question Expired"},
            },
            "subtitle": {
                "tag": "plain_text",
                "content": "未在规定时间内回答",
                "i18n_content": {"zh_cn": "未在规定时间内回答", "en_us": "No response within time limit"},
            },
            "text_tag_list": [{
                "tag": "text_tag",
                "text": {"tag": "plain_text", "content": "已过期"},
                "color": "neutral",
            }],
            "template": "grey",
        },
        "body": {"elements": elements},
    }


# ---------------------------------------------------------------------------
# Card Kit API helpers
# ---------------------------------------------------------------------------


async def _get_tenant_token(adapter: Any) -> str:
    """Get tenant access token from adapter credentials."""
    import httpx

    base_url = (
        "https://open.larksuite.com/open-apis"
        if getattr(adapter, "_domain", "") == "lark"
        else "https://open.feishu.cn/open-apis"
    )
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{base_url}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": adapter._app_id,
                "app_secret": adapter._app_secret,
            },
        )
        data = r.json()
        token = data.get("tenant_access_token", "")
        if not token:
            raise RuntimeError(f"Token fetch failed: {data.get('msg', 'unknown')}")
        return token


async def create_card_entity(adapter: Any, card: dict) -> Optional[str]:
    """Create a Card Kit v2 card entity. Returns card_id or None.

    POST /cardkit/v1/cards
    """
    import httpx

    base_url = (
        "https://open.larksuite.com/open-apis"
        if getattr(adapter, "_domain", "") == "lark"
        else "https://open.feishu.cn/open-apis"
    )

    try:
        token = await _get_tenant_token(adapter)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        payload = json.dumps({
            "type": "card_json",
            "data": json.dumps(card, ensure_ascii=False),
        }, ensure_ascii=False)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{base_url}/cardkit/v1/cards",
                headers=headers,
                content=payload.encode(),
            )
            data = resp.json()
            if data.get("code") != 0:
                log.warning("[ask_user] Card creation failed: %s", data.get("msg"))
                return None
            card_id = data.get("data", {}).get("card_id")
            if not card_id:
                log.warning("[ask_user] Card creation returned no card_id")
                return None
            return card_id
    except Exception as exc:
        log.error("[ask_user] create_card_entity error: %s", exc)
        return None


async def send_card_by_card_id(
    adapter: Any,
    chat_id: str,
    card_id: str,
    reply_to_message_id: Optional[str] = None,
    reply_in_thread: bool = False,
) -> bool:
    """Send an interactive card message referencing a Card Kit card_id.

    Matches openclaw sendCardByCardId().
    """
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest, CreateMessageRequestBody,
            ReplyMessageRequest, ReplyMessageRequestBody,
        )

        lark_domain = lark.LARK_DOMAIN if getattr(adapter, "_domain", "") == "lark" else lark.FEISHU_DOMAIN
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

        if reply_to_message_id:
            body = (
                ReplyMessageRequestBody.builder()
                .msg_type("interactive")
                .content(card_content)
                .build()
            )
            request = (
                ReplyMessageRequest.builder()
                .message_id(reply_to_message_id)
                .request_body(body)
                .build()
            )
            resp = await asyncio.to_thread(lark_client.im.v1.message.reply, request)
        else:
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
            log.info("[ask_user] Card sent to chat %s (card_id=%s)",
                     chat_id[:12], card_id)
            return True

        log.warning("[ask_user] Card send failed: code=%s", getattr(resp, "code", "?"))
        return False

    except Exception as exc:
        log.error("[ask_user] send_card_by_card_id error: %s", exc)
        return False


async def update_card(adapter: Any, card_id: str, card: dict, sequence: int) -> bool:
    """Update a card entity via Card Kit API.

    PUT /cardkit/v1/cards/{card_id}
    Matches lark-oapi UpdateCardRequest / openclaw updateCardKitCard().
    """
    import httpx

    base_url = (
        "https://open.larksuite.com/open-apis"
        if getattr(adapter, "_domain", "") == "lark"
        else "https://open.feishu.cn/open-apis"
    )

    try:
        token = await _get_tenant_token(adapter)

        # lark-oapi UpdateCardRequest uses PUT /cardkit/v1/cards/{card_id}.
        # PATCH returns 404 on Feishu and leaves expired/answered cards visually active.
        payload = json.dumps({
            # UpdateCardRequestBody.card is a Card object, not a JSON string.
            # Feishu rejects the stringified form with:
            #   Invalid parameter type in json: Card
            "card": {
                "type": "card_json",
                "data": json.dumps(card, ensure_ascii=False),
            },
            "sequence": sequence,
            "uuid": f"c_{card_id}_{sequence}",
        }, ensure_ascii=False)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.put(
                f"{base_url}/cardkit/v1/cards/{card_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                content=payload.encode(),
            )
            data = resp.json()
            if data.get("code") != 0:
                log.warning("[ask_user] Card update failed: code=%s msg=%s",
                            data.get("code"), data.get("msg"))
                return False
            return True

    except Exception as exc:
        log.warning("[ask_user] update_card error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Tool handler — NON-BLOCKING (returns immediately)
# ---------------------------------------------------------------------------


async def ask_user_handler(args: dict[str, Any], **kw: Any) -> str:
    """Send questions to the user via interactive card and return immediately.

    Does NOT wait for user response. Returns {status: 'pending', questionId}.
    The user's answers will arrive as a synthetic message in a new turn.
    """
    from marneo.gateway.pending_questions import (
        PendingQuestionContext,
        store_pending_question,
    )

    # ── Parse and validate questions ──────────────────────────────────────
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

    # Validate and normalize (max 6 questions, max 10 options each)
    questions: list[dict] = []
    for q in questions_raw[:6]:
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

    # ── Get context ───────────────────────────────────────────────────────
    ctx = ask_user_ctx.get()
    if ctx is None:
        return tool_error("ask_user is only available in Feishu chat context.")

    chat_id = ctx.chat_id
    adapter = ctx.adapter
    if not chat_id or not adapter:
        return tool_error("Missing chat_id or adapter in ask_user context")

    question_id = uuid.uuid4().hex
    log.info("[ask_user] Creating question: id=%s, count=%d, chat=%s",
             question_id, len(questions), chat_id[:12])

    # ── 1. Build and create card entity ───────────────────────────────────
    card = build_ask_user_card(questions, question_id)
    card_id = await create_card_entity(adapter, card)
    if not card_id:
        return tool_error("Failed to create question card")

    # ── 2. Send card as interactive message ───────────────────────────────
    sent = await send_card_by_card_id(
        adapter, chat_id, card_id,
        reply_to_message_id=ctx.msg_id or None,
        reply_in_thread=bool(ctx.thread_id),
    )
    if not sent:
        return tool_error("Failed to send question card to Feishu")

    # ── 3. Store context for card action handler ──────────────────────────
    pending_ctx = PendingQuestionContext(
        question_id=question_id,
        chat_id=chat_id,
        account_id=adapter._app_id,
        sender_open_id=ctx.sender_open_id,
        card_id=card_id,
        questions=questions,
        message_id=ctx.msg_id,
        chat_type=ctx.chat_type,
        thread_id=ctx.thread_id,
        card_sequence=1,
        submitted=False,
        adapter=adapter,
    )
    store_pending_question(pending_ctx)

    # ── 4. Return immediately — answers arrive via synthetic message ──────
    log.info("[ask_user] Question %s card sent, returning pending status", question_id)
    return tool_result(
        status="pending",
        questionId=question_id,
        message=(
            "Question card sent to the user. Their answers will arrive as a follow-up message "
            "in this conversation. Do NOT call this tool again for the same question \u2014 just wait "
            "for the response message."
        ),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="ask_user",
    description=(
        "Ask the user a question via an interactive Feishu card. "
        "Returns immediately after sending the card. "
        "The user's answers will arrive as a new message in the conversation. "
        "Do NOT poll or re-call this tool \u2014 just wait for the response message. "
        "For selection questions, provide options (renders as dropdown). "
        "For free-text input, set options to an empty array."
    ),
    schema={
        "name": "ask_user",
        "description": (
            "Ask the user a question via an interactive Feishu card. "
            "Returns immediately after sending the card. "
            "The user's answers will arrive as a new message in the conversation. "
            "Do NOT poll or re-call this tool \u2014 just wait for the response message."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The question to ask the user",
                            },
                            "header": {
                                "type": "string",
                                "description": "Short label for the question (max 12 chars)",
                            },
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {
                                            "type": "string",
                                            "description": "Display text for this option",
                                        },
                                        "description": {
                                            "type": "string",
                                            "description": "Explanation of what this option means",
                                        },
                                    },
                                    "required": ["label", "description"],
                                },
                                "maxItems": 10,
                                "description": (
                                    "Available choices. Renders as a dropdown. "
                                    "Leave empty ([]) for free-text input."
                                ),
                            },
                            "multiSelect": {
                                "type": "boolean",
                                "description": "Whether multiple options can be selected (ignored when options is empty)",
                            },
                        },
                        "required": ["question", "header", "options", "multiSelect"],
                    },
                    "minItems": 1,
                    "maxItems": 6,
                    "description": "Questions to ask the user (1-6 questions)",
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
