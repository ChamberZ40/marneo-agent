# marneo/tools/core/web.py
"""Web tools: web_fetch (URL -> plain text), web_search (DuckDuckGo)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from marneo.tools.registry import registry, tool_result, tool_error

_MAX_CONTENT = 50_000
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarneoAgent/1.0)"}


def _html_to_text(html: str) -> str:
    """Strip HTML tags to plain text."""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<(br|p|div|h[1-6]|li|tr)[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", "", html)
    for ent, ch in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " "), ("&quot;", '"'), ("&#39;", "'")]:
        html = html.replace(ent, ch)
    lines = [ln.strip() for ln in html.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _safe_url(url: str) -> bool:
    try:
        return urlparse(url).scheme in ("http", "https")
    except Exception:
        return False


def web_fetch(args: dict[str, Any], **kw: Any) -> str:
    url = args.get("url", "").strip()
    if not url:
        return tool_error("url is required")
    if not _safe_url(url):
        return tool_error(f"Only http/https URLs allowed: {url}")
    try:
        import httpx
        resp = httpx.get(url, headers=_HEADERS, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "html" in content_type:
            text = _html_to_text(resp.text)
        elif "json" in content_type:
            # Don't truncate JSON mid-stream — return as-is up to limit, note if truncated
            raw = resp.text
            truncated = len(raw) > _MAX_CONTENT
            text = raw[:_MAX_CONTENT] if truncated else raw
            if truncated:
                return tool_result(url=url, content=text, status=resp.status_code,
                                   note="JSON response truncated — content may be incomplete")
        else:
            text = resp.text
        if len(text) > _MAX_CONTENT:
            text = text[:_MAX_CONTENT] + "\n... (truncated)"
        return tool_result(url=url, content=text, status=resp.status_code)
    except Exception as exc:
        return tool_error(str(exc))


def web_search(args: dict[str, Any], **kw: Any) -> str:
    query = args.get("query", "").strip()
    try:
        limit = max(1, min(int(args.get("limit", 5)), 10))
    except (ValueError, TypeError):
        limit = 5
        return tool_error("query is required")
    try:
        import httpx
        resp = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", ""),
                "url": data.get("AbstractURL", ""),
                "content": data["AbstractText"],
            })
        for topic in data.get("RelatedTopics", [])[:limit]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic["Text"][:100],
                    "url": topic.get("FirstURL", ""),
                    "content": topic["Text"],
                })
        if not results:
            return tool_result(query=query, results=[], note="No results. Try web_fetch on a specific URL.")
        return tool_result(query=query, results=results[:limit])
    except Exception as exc:
        return tool_error(str(exc))


registry.register(
    name="web_fetch",
    description="Fetch a URL and return its content as plain text.",
    schema={
        "name": "web_fetch",
        "description": "Fetch a web page and return its content as plain text. Only http/https URLs.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
        },
    },
    handler=web_fetch,
    emoji="🌐",
    max_result_chars=60_000,
)

registry.register(
    name="web_search",
    description="Search the web using DuckDuckGo. Returns titles, URLs, snippets.",
    schema={
        "name": "web_search",
        "description": "Search the web via DuckDuckGo. Returns titles, URLs, text snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 5, max 10)", "default": 5},
            },
            "required": ["query"],
        },
    },
    handler=web_search,
    emoji="🔍",
    max_result_chars=20_000,
)
