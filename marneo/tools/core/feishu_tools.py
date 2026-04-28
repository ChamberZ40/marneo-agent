# marneo/tools/core/feishu_tools.py
"""Feishu-specific tools: @mention messaging, contact search, file sending.

Ported from openclaw/extensions/feishu/src/mention.ts.
"""
from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
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
    """Search Feishu users — try group member list first, then contact search."""
    query = args.get("query", "").strip()
    chat_id = args.get("chat_id", "").strip()
    if not query:
        return tool_error("query is required")

    try:
        import shutil, subprocess
        lark_bin = shutil.which("lark-cli")
        if not lark_bin:
            return tool_error("lark-cli not installed")

        # If chat_id provided, search group members first (more reliable)
        if chat_id:
            result = subprocess.run(
                [lark_bin, "im", "chat.members", "get",
                 "--params", json.dumps({"chat_id": chat_id}),
                 "--as", "bot", "--format", "json"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                return tool_result(raw=result.stdout.strip(), query=query, source="chat_members")

        # Fallback: try contact search
        result = subprocess.run(
            [lark_bin, "api", "GET", "/open-apis/search/v1/user",
             "--params", json.dumps({"query": query, "page_size": "5"}),
             "--as", "bot", "--format", "json"],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip() or result.stderr.strip()
        return tool_result(raw=output, query=query, source="contact_search")
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
    description="Search Feishu users or list group members to find open_id.",
    schema={
        "name": "feishu_search_user",
        "description": "Search for users or list group members. Provide chat_id to list members of a specific group.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name to search for"},
                "chat_id": {"type": "string", "description": "Optional: group chat_id to list members from (more reliable)"},
            },
            "required": ["query"],
        },
    },
    handler=feishu_search_user,
    emoji="🔍",
)


def feishu_create_doc(args: dict[str, Any], **kw: Any) -> str:
    """Create a Feishu document — delegates to lark_cli."""
    title = args.get("title", "").strip()
    content = args.get("content", "").strip()
    if not title and not content:
        return tool_error("title or content is required")
    import shlex
    from marneo.tools.core.lark_cli import lark_cli
    parts = ["docs", "+create"]
    if title:
        parts.extend(["--title", shlex.quote(title)])
    if content:
        parts.extend(["--content", shlex.quote(content)])
    return lark_cli({"command": " ".join(parts)})


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


# ── File / image sending ────────────────────────────────────────────────────

_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})
_MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 10 MB
_MAX_FILE_BYTES = 20 * 1024 * 1024    # 20 MB


def _is_image_file(file_path: str) -> bool:
    """Detect if a file should be uploaded as an image based on extension and MIME."""
    ext = Path(file_path).suffix.lower()
    if ext in _IMAGE_EXTENSIONS:
        return True
    mime, _ = mimetypes.guess_type(file_path)
    return mime is not None and mime.startswith("image/")


def _get_feishu_credentials() -> tuple[str, str, str]:
    """Return (app_id, app_secret, domain) from any configured employee.

    Raises ValueError if no credentials are found.
    """
    from marneo.employee.feishu_config import list_configured_employees, load_feishu_config

    for emp in list_configured_employees():
        cfg = load_feishu_config(emp)
        if cfg and cfg.is_complete:
            return cfg.app_id, cfg.app_secret, cfg.domain
    raise ValueError("No Feishu credentials configured")


def _build_client(app_id: str, app_secret: str, domain: str) -> Any:
    """Build a lark-oapi Client (sync helper)."""
    import lark_oapi as lark

    lark_domain = lark.LARK_DOMAIN if domain == "lark" else lark.FEISHU_DOMAIN
    return (
        lark.Client.builder()
        .app_id(app_id).app_secret(app_secret).domain(lark_domain).build()
    )


def feishu_send_file(args: dict[str, Any], **kw: Any) -> str:
    """Upload a local file/image to Feishu and send it to a chat."""
    file_path = args.get("file_path", "").strip()
    chat_id = args.get("chat_id", "").strip()
    file_name = args.get("file_name", "").strip()

    if not file_path:
        return tool_error("file_path is required")
    if not chat_id:
        return tool_error("chat_id is required")
    if not os.path.isfile(file_path):
        return tool_error(f"File not found: {file_path}")

    file_size = os.path.getsize(file_path)
    is_image = _is_image_file(file_path)

    if is_image and file_size > _MAX_IMAGE_BYTES:
        return tool_error(f"Image too large ({file_size} bytes). Max is {_MAX_IMAGE_BYTES} bytes (10 MB).")
    if not is_image and file_size > _MAX_FILE_BYTES:
        return tool_error(f"File too large ({file_size} bytes). Max is {_MAX_FILE_BYTES} bytes (20 MB).")

    if not file_name:
        file_name = Path(file_path).name

    try:
        app_id, app_secret, domain = _get_feishu_credentials()
    except ValueError as exc:
        return tool_error(str(exc))

    try:
        import asyncio
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest, CreateMessageRequestBody,
        )

        client = _build_client(app_id, app_secret, domain)

        async def _upload_and_send() -> dict:
            if is_image:
                key = await _upload_image(client, file_path)
                content = json.dumps({"image_key": key})
                msg_type = "image"
            else:
                key = await _upload_file(client, file_path, file_name)
                content = json.dumps({"file_key": key, "file_name": file_name})
                msg_type = "file"

            body = (
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type(msg_type)
                .content(content)
                .build()
            )
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(body)
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message.create, req)

            if resp and getattr(resp, "success", lambda: False)():
                msg_id = getattr(getattr(resp, "data", None), "message_id", "")
                return {"ok": True, "message_id": msg_id, "file_name": file_name, "msg_type": msg_type}

            return {
                "error": (
                    f"Send failed: code={getattr(resp, 'code', '?')} "
                    f"msg={getattr(resp, 'msg', '?')}"
                ),
            }

        from marneo.tools.registry import _run_async
        result = _run_async(lambda: _upload_and_send())
        return json.dumps(result, ensure_ascii=False)

    except Exception as exc:
        return tool_error(str(exc))


async def _upload_image(client: Any, file_path: str) -> str:
    """Upload an image to Feishu. Returns image_key.

    Uses POST /open-apis/im/v1/images with image_type=message.
    """
    import asyncio
    from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody

    with open(file_path, "rb") as f:
        body = (
            CreateImageRequestBody.builder()
            .image_type("message")
            .image(f)
            .build()
        )
        req = CreateImageRequest.builder().request_body(body).build()
        resp = await asyncio.to_thread(client.im.v1.image.create, req)

    if not resp or not getattr(resp, "success", lambda: False)():
        code = getattr(resp, "code", "?")
        msg = getattr(resp, "msg", "?")
        raise RuntimeError(f"Image upload failed: code={code} msg={msg}")

    data = getattr(resp, "data", None)
    image_key = getattr(data, "image_key", "") if data else ""
    if not image_key:
        raise RuntimeError("Image upload returned empty image_key")
    return image_key


async def _upload_file(client: Any, file_path: str, file_name: str) -> str:
    """Upload a general file to Feishu. Returns file_key.

    Uses POST /open-apis/im/v1/files with file_type=stream.
    """
    import asyncio
    from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody

    with open(file_path, "rb") as f:
        body = (
            CreateFileRequestBody.builder()
            .file_type("stream")
            .file_name(file_name)
            .file(f)
            .build()
        )
        req = CreateFileRequest.builder().request_body(body).build()
        resp = await asyncio.to_thread(client.im.v1.file.create, req)

    if not resp or not getattr(resp, "success", lambda: False)():
        code = getattr(resp, "code", "?")
        msg = getattr(resp, "msg", "?")
        raise RuntimeError(f"File upload failed: code={code} msg={msg}")

    data = getattr(resp, "data", None)
    file_key = getattr(data, "file_key", "") if data else ""
    if not file_key:
        raise RuntimeError("File upload returned empty file_key")
    return file_key


registry.register(
    name="feishu_send_file",
    description="Send a file or image to a Feishu chat.",
    schema={
        "name": "feishu_send_file",
        "description": (
            "Send a file or image to a Feishu chat. "
            "Uploads the file to Feishu and sends it as a chat attachment. "
            "Images (jpg/png/gif/webp) are sent as image messages; "
            "other files are sent as file attachments. "
            "Max 10 MB for images, 20 MB for other files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to the local file"},
                "chat_id": {"type": "string", "description": "Target chat ID (oc_xxx) from message context"},
                "file_name": {"type": "string", "description": "Optional display name (defaults to filename from path)"},
            },
            "required": ["file_path", "chat_id"],
        },
    },
    handler=feishu_send_file,
    emoji="📎",
)
