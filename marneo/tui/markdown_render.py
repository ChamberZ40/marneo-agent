# marneo/tui/markdown_render.py
"""Simple streaming inline Markdown → ANSI renderer (line by line)."""
from __future__ import annotations
import re

_RST  = "\033[0m"
_TEXT = "\033[38;2;224;224;224m"
_PRI  = "\033[1;38;2;255;102;17m"
_DIM  = "\033[38;2;85;85;85m"

_in_code_block = False


def render_line(line: str) -> str:
    """Render one line of Markdown to ANSI string."""
    global _in_code_block

    if line.startswith("```"):
        _in_code_block = not _in_code_block
        return f"{_DIM}{'─' * 36}{_RST}"

    if _in_code_block:
        return f"{_DIM}  {line}{_RST}"

    if line.startswith("### "):
        return f"\033[1m{_inline(line[4:])}\033[0m"
    if line.startswith("## "):
        return f"{_PRI}\033[1m{_inline(line[3:])}\033[0m"
    if line.startswith("# "):
        return f"{_PRI}\033[1m{_inline(line[2:])}\033[0m"
    if line.startswith("> "):
        return f"{_DIM}▌ {_inline(line[2:])}{_RST}"
    if line.strip() in ("---", "***", "___"):
        return f"{_DIM}{'─' * 36}{_RST}"

    stripped = line.lstrip()
    indent = " " * (len(line) - len(stripped))
    if stripped.startswith(("- ", "* ", "+ ")):
        return f"{indent}{_PRI}•{_RST} {_TEXT}{_inline(stripped[2:])}{_RST}"
    m = re.match(r"^(\d+)\. (.+)$", stripped)
    if m:
        return f"{indent}{_PRI}{m.group(1)}.{_RST} {_TEXT}{_inline(m.group(2))}{_RST}"

    return f"{_TEXT}{_inline(line)}{_RST}"


def _inline(text: str) -> str:
    """Apply inline Markdown (bold, italic, code)."""
    text = re.sub(r"`([^`]+)`", f"{_DIM}`\\1`{_RST}{_TEXT}", text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\033[1m\033[3m\1\033[0m", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\033[1m\1\033[0m", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\033[3m\1\033[0m", text)
    return text
