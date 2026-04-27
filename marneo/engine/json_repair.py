# marneo/engine/json_repair.py
"""Best-effort repair of malformed JSON from LLM tool call arguments.

Ported from hermes-agent/tools/model_tools.py JSON repair pass.
Handles: trailing commas, unclosed brackets, Python None/True/False,
single-quoted strings, and common LLM quirks.
"""
from __future__ import annotations

import json
import re

# Python literals → JSON
_PY_LITERALS = [
    (re.compile(r"\bNone\b"), "null"),
    (re.compile(r"\bTrue\b"), "true"),
    (re.compile(r"\bFalse\b"), "false"),
]

# Trailing commas before closing bracket/brace
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def repair_json(raw: str) -> str:
    """Attempt to fix common JSON errors and return a valid JSON string.

    Returns the original string if no repair is needed or if repair fails.
    """
    s = raw.strip()
    if not s:
        return "{}"

    # Fast path: already valid
    try:
        json.loads(s)
        return s
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences (```json ... ```)
    if s.startswith("```"):
        lines = s.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    # Replace Python literals
    for pat, repl in _PY_LITERALS:
        s = pat.sub(repl, s)

    # Remove trailing commas
    s = _TRAILING_COMMA.sub(r"\1", s)

    # Single-quoted strings → double-quoted (simple heuristic: not inside double quotes)
    # Only apply if no double quotes exist (to avoid breaking valid JSON)
    if '"' not in s and "'" in s:
        s = s.replace("'", '"')

    # Close unclosed brackets/braces
    opens = 0
    squares = 0
    in_string = False
    escape = False
    for ch in s:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            opens += 1
        elif ch == "}":
            opens -= 1
        elif ch == "[":
            squares += 1
        elif ch == "]":
            squares -= 1

    if opens > 0:
        s += "}" * opens
    if squares > 0:
        s += "]" * squares

    # Validate
    try:
        json.loads(s)
        return s
    except json.JSONDecodeError:
        # Last resort: return original — caller handles the error
        return raw
