# marneo/tools/core/memory_tools.py
"""Memory tools: recall_memory, get_skill, add_core_memory, add_episode.

Session-scoped — NOT registered in the global registry.
Injected per-session via SessionMemory.get_memory_tools().
"""
from __future__ import annotations

from typing import Any, Optional

from marneo.tools.registry import tool_result, tool_error


def recall_memory(
    args: dict[str, Any],
    _retriever: Any = None,
    **kw: Any,
) -> str:
    query = args.get("query", "").strip()
    n = min(int(args.get("n", 3)), 5)
    filter_type = args.get("type", "")

    if not query:
        return tool_error("query is required")

    if _retriever is None:
        return tool_result(results=[], note="Memory retriever not initialized")

    try:
        results = _retriever.retrieve(query, n=n)
        if filter_type:
            results = [r for r in results if r.source == filter_type]
        items = [
            {"id": r.id, "content": r.content, "type": r.type,
             "source": r.source, "skill_id": r.skill_id}
            for r in results
        ]
        return tool_result(results=items, query=query)
    except Exception as exc:
        return tool_error(str(exc))


def get_skill(args: dict[str, Any], **kw: Any) -> str:
    skill_id = args.get("skill_id", "").strip()
    if not skill_id:
        return tool_error("skill_id is required")
    try:
        from marneo.memory.skill_index import get_skill_content
        content = get_skill_content(skill_id)
        if content.startswith("[Skill not found"):
            return tool_error(f"Skill not found: {skill_id}")
        return tool_result(skill_id=skill_id, content=content)
    except Exception as exc:
        return tool_error(str(exc))


def add_core_memory(
    args: dict[str, Any],
    _core_memory: Any = None,
    **kw: Any,
) -> str:
    content = args.get("content", "").strip()
    reason = args.get("reason", "").strip()
    if not content:
        return tool_error("content is required")
    if _core_memory is None:
        return tool_error("Core memory not available for this session")
    try:
        _core_memory.add(content, source="llm")
        return tool_result(ok=True, content=content, reason=reason)
    except Exception as exc:
        return tool_error(str(exc))


def add_episode(
    args: dict[str, Any],
    _store: Any = None,
    **kw: Any,
) -> str:
    content = args.get("content", "").strip()
    ep_type = args.get("type", "general")
    tags = args.get("tags", [])
    if not content:
        return tool_error("content is required")
    if _store is None:
        return tool_result(ok=True, note="Episode store not available")
    try:
        from marneo.memory.episodes import Episode
        ep = Episode(content=content, type=ep_type, tags=tags if isinstance(tags, list) else [])
        ep_id = _store.add(ep)
        return tool_result(ok=True, id=ep_id)
    except Exception as exc:
        return tool_error(str(exc))


# Tool schemas for LLM function calling
MEMORY_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Recall relevant work experience or skills. Use when you need past solutions or relevant skills.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "n": {"type": "integer", "description": "Max results (default 3)", "default": 3},
                    "type": {"type": "string", "description": "Filter: 'skill' or 'episode'"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_skill",
            "description": "Get full content of a skill by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "description": "Skill file ID (without .md)"},
                },
                "required": ["skill_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_core_memory",
            "description": "Save a critical constraint to core memory. Use when user states an important rule.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The rule to remember"},
                    "reason": {"type": "string", "description": "Why this is important"},
                },
                "required": ["content", "reason"],
            },
        },
    },
]
