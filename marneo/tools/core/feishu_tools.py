# marneo/tools/core/feishu_tools.py
"""Feishu-specific tools: @mention messaging, contact search.

Ported from openclaw/extensions/feishu/src/mention.ts.
"""
from __future__ import annotations

import json
from typing import Any

from marneo.tools.registry import registry, tool_result, tool_error


def _build_mention_text(mentions: list[dict], text: str = "") -> str:
    """Build Feishu text message with @mention tags (openclaw format).

    Format: <at user_id="ou_xxx">Name</at> message text
    """
    parts = []
    for m in mentions:
        open_id = m.get("open_id", "").strip()
        name = m.get("name", "用户").strip()
        if open_id == "all":
            parts.append('<at user_id="all">所有人</at>')
        elif open_id:
            parts.append(f'<at user_id="{open_id}">{name}</at>')
    if text:
        parts.append(text)
    return " ".join(parts)


def feishu_send_mention(args: dict[str, Any], **kw: Any) -> str:
    """Send a Feishu message with @mention to one or more users."""
    chat_id = args.get("chat_id", "").strip()
    text = args.get("text", "").strip()
    mentions = args.get("mentions", [])  # list of {"open_id": "ou_xxx", "name": "张三"}
    reply_to = args.get("reply_to_msg_id", "")

    if not chat_id:
        return tool_error("chat_id is required")
    if not mentions and not text:
        return tool_error("mentions or text is required")

    if not isinstance(mentions, list):
        mentions = []

    content_text = _build_mention_text(mentions, text)
    content = json.dumps({"text": content_text}, ensure_ascii=False)

    try:
        # Get Feishu adapter credentials from any configured employee
        from marneo.employee.feishu_config import list_configured_employees, load_feishu_config
        app_id = app_secret = domain = ""
        for emp in list_configured_employees():
            cfg = load_feishu_config(emp)
            if cfg and cfg.is_complete:
                app_id, app_secret, domain = cfg.app_id, cfg.app_secret, cfg.domain
                break
        if not app_id:
            return tool_error("No Feishu credentials configured")

        import asyncio
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest, CreateMessageRequestBody,
            ReplyMessageRequest, ReplyMessageRequestBody,
        )

        lark_domain = lark.LARK_DOMAIN if domain == "lark" else lark.FEISHU_DOMAIN
        client = (
            lark.Client.builder()
            .app_id(app_id).app_secret(app_secret).domain(lark_domain).build()
        )

        async def _send() -> dict:
            if reply_to:
                body = (
                    ReplyMessageRequestBody.builder()
                    .msg_type("text").content(content).build()
                )
                req = (
                    ReplyMessageRequest.builder()
                    .message_id(reply_to).request_body(body).build()
                )
                resp = await asyncio.to_thread(client.im.v1.message.reply, req)
            else:
                body = (
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id).msg_type("text").content(content).build()
                )
                req = (
                    CreateMessageRequest.builder()
                    .receive_id_type("chat_id").request_body(body).build()
                )
                resp = await asyncio.to_thread(client.im.v1.message.create, req)

            if resp and getattr(resp, "success", lambda: False)():
                msg_id = getattr(getattr(resp, "data", None), "message_id", "")
                return {"ok": True, "message_id": msg_id, "text": content_text}
            return {"error": f"Send failed: code={getattr(resp, 'code', '?')} msg={getattr(resp, 'msg', '?')}"}

        from marneo.tools.registry import _run_async
        result = _run_async(lambda: _send())
        return json.dumps(result, ensure_ascii=False)

    except Exception as exc:
        return tool_error(str(exc))


def feishu_search_user(args: dict[str, Any], **kw: Any) -> str:
    """Search Feishu users via lark-cli (uses existing App permissions)."""
    query = args.get("query", "").strip()
    if not query:
        return tool_error("query is required")

    try:
        import shutil, subprocess
        lark_bin = shutil.which("lark-cli")
        if not lark_bin:
            return tool_error("lark-cli not installed")

        result = subprocess.run(
            [lark_bin, "contact", "+search", "--keyword", query,
             "--as", "bot", "--format", "json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            # fallback: try without +search shortcut
            result = subprocess.run(
                [lark_bin, "contact", "users", "batch_get_id",
                 "--emails", query, "--as", "bot", "--format", "json"],
                capture_output=True, text=True, timeout=15,
            )
        output = result.stdout.strip() or result.stderr.strip()
        return tool_result(raw=output, query=query)
    except Exception as exc:
        return tool_error(str(exc))


# ── Register ──────────────────────────────────────────────────────────────────

registry.register(
    name="feishu_send_mention",
    description="Send a Feishu message with @mention to specific users or bots.",
    schema={
        "name": "feishu_send_mention",
        "description": (
            "Send a Feishu message with @mention. "
            "To find someone's open_id: use lark_cli with 'chat members --chat-id <chat_id>' "
            "to list group members and find the target person. "
            "The sender's open_id and chat_id are in the message prefix."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string", "description": "Target chat_id (oc_xxx) — available from message context"},
                "mentions": {
                    "type": "array",
                    "description": "Users to @mention. Get open_id from lark_cli chat members list.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "open_id": {"type": "string", "description": "User open_id (ou_xxx)"},
                            "name": {"type": "string", "description": "User display name"},
                        },
                    },
                },
                "text": {"type": "string", "description": "Message text after the @mentions"},
                "reply_to_msg_id": {"type": "string", "description": "Optional: reply to this message_id"},
            },
            "required": ["chat_id"],
        },
    },
    handler=feishu_send_mention,
    emoji="📢",
)

registry.register(
    name="feishu_search_user",
    description="Search Feishu users by name/email to get their open_id for @mention.",
    schema={
        "name": "feishu_search_user",
        "description": "Search for Feishu users by name, email, or phone. Returns open_id for use in feishu_send_mention.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name, email, or phone to search"},
            },
            "required": ["query"],
        },
    },
    handler=feishu_search_user,
    emoji="🔍",
)


def feishu_create_doc(args: dict[str, Any], **kw: Any) -> str:
    """Create a Feishu document — delegates to lark_cli docs +create."""
    title = args.get("title", "").strip()
    content = args.get("content", "").strip()
    if not title and not content:
        return tool_error("title or content is required")
    from marneo.tools.core.lark_cli import lark_cli
    cmd = "docs +create"
    if title:
        cmd += f' --title "{title}"'
    if content:
        cmd += f' --content "{content}"'
    return lark_cli({"command": cmd})


registry.register(
    name="feishu_create_doc",
    description="Create a Feishu document with title and markdown content.",
    schema={
        "name": "feishu_create_doc",
        "description": "Create a Feishu cloud document. Use for 'create document', 'write doc', '创建文档' requests.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Document title"},
                "content": {"type": "string", "description": "Document content in Markdown"},
            },
        },
    },
    handler=feishu_create_doc,
    emoji="📄",
)
