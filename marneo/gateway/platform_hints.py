# marneo/gateway/platform_hints.py
"""Platform-specific formatting hints for system prompts.

Hermes-agent pattern: inject platform capabilities so the LLM adapts
output format to the channel (markdown, cards, embeds, etc.).
"""
from __future__ import annotations

_HINTS: dict[str, str] = {
    "feishu": (
        "Platform: Feishu (飞书). "
        "Formatting: Markdown is rendered (headers, bold, code blocks, lists). "
        "Messages support 4000 chars max. "
        "Streaming card mode is active — your text response IS the reply, shown as a live-updating card. "
        "IMPORTANT: Do NOT use feishu_send_mention to reply to the sender — your card response is already visible to them. "
        "Only use feishu_send_mention when explicitly asked to @mention a DIFFERENT person or bot. "
        "You can create docs with feishu_create_doc tool."
    ),
    "telegram": (
        "Platform: Telegram. "
        "Formatting: Markdown v2 (bold, italic, code, links). "
        "Messages support 4096 chars max. "
        "No card or embed support — use plain text with markdown."
    ),
    "wechat": (
        "Platform: WeChat. "
        "Formatting: Plain text only (no markdown rendering). "
        "Messages support 2048 chars max. "
        "Keep responses concise and use line breaks for readability."
    ),
    "discord": (
        "Platform: Discord. "
        "Formatting: Markdown (bold, italic, code blocks, spoilers). "
        "Messages support 2000 chars max. "
        "You can use embeds for structured data."
    ),
    "cli": (
        "Platform: CLI terminal. "
        "Formatting: Full markdown rendered in terminal. "
        "No message length limit. "
        "Code blocks are syntax-highlighted."
    ),
}

_DEFAULT_HINT = (
    "Platform: Unknown. "
    "Formatting: Use plain text. Keep responses concise."
)


def get_platform_hint(platform: str) -> str:
    """Return platform-specific hint string for system prompt injection.

    platform: "feishu", "feishu:laoqi", "telegram", "wechat", "discord", "cli"
    """
    # Extract base platform from "feishu:employee_name" style
    base = platform.split(":")[0].lower() if platform else ""
    return _HINTS.get(base, _DEFAULT_HINT)
