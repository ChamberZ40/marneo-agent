# marneo/tools/core/files.py
"""File tools: read_file, write_file, edit_file, glob_files, grep_files."""
from __future__ import annotations

import glob as _glob
import json
import re
from pathlib import Path
from typing import Any

from marneo.tools.registry import registry, tool_result, tool_error

_MAX_READ_CHARS = 100_000


def read_file(args: dict[str, Any], **kw: Any) -> str:
    path = args.get("path", "")
    offset = int(args.get("offset", 1))
    limit = int(args.get("limit", 500))
    if not path:
        return tool_error("path is required")
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return tool_error(f"File not found: {path}")
        if not p.is_file():
            return tool_error(f"Not a file: {path}")
        raw = p.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        total = len(lines)
        start = max(0, offset - 1)
        end = min(start + limit + 1, total)
        selected = lines[start:end]
        numbered = "\n".join(f"{i + start + 1}\t{line}" for i, line in enumerate(selected))
        if len(numbered) > _MAX_READ_CHARS:
            numbered = numbered[:_MAX_READ_CHARS] + "\n... (truncated)"
        return tool_result(content=numbered, path=path, lines=total, offset=start + 1, returned=len(selected))
    except Exception as exc:
        return tool_error(str(exc))


def write_file(args: dict[str, Any], **kw: Any) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        return tool_error("path is required")
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return tool_result(ok=True, path=str(p), bytes=len(content.encode()))
    except Exception as exc:
        return tool_error(str(exc))


def edit_file(args: dict[str, Any], **kw: Any) -> str:
    path = args.get("path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    if not path:
        return tool_error("path is required")
    if old_string == "":
        return tool_error("old_string is required")
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return tool_error(f"File not found: {path}")
        original = p.read_text(encoding="utf-8", errors="replace")
        if old_string not in original:
            return tool_error(f"old_string not found in {path}")
        count = original.count(old_string)
        if count > 1:
            return tool_error(f"old_string matches {count} locations — make it more specific")
        updated = original.replace(old_string, new_string, 1)
        p.write_text(updated, encoding="utf-8")
        return tool_result(ok=True, path=str(p))
    except Exception as exc:
        return tool_error(str(exc))


def glob_files(args: dict[str, Any], **kw: Any) -> str:
    pattern = args.get("pattern", "")
    base = args.get("path", ".")
    if not pattern:
        return tool_error("pattern is required")
    try:
        base_path = Path(base).expanduser()
        full_pattern = str(base_path / "**" / pattern) if "/" not in pattern else str(base_path / pattern)
        matches = _glob.glob(full_pattern, recursive=True)
        if not matches:
            matches = _glob.glob(str(base_path / pattern))
        matches = sorted(str(Path(m)) for m in matches if Path(m).is_file())[:200]
        return tool_result(files=matches, count=len(matches))
    except Exception as exc:
        return tool_error(str(exc))


def grep_files(args: dict[str, Any], **kw: Any) -> str:
    pattern = args.get("pattern", "")
    path = args.get("path", ".")
    file_pattern = args.get("glob", "")
    case_insensitive = bool(args.get("case_insensitive", False))
    if not pattern:
        return tool_error("pattern is required")
    try:
        base = Path(path).expanduser()
        flags = re.IGNORECASE if case_insensitive else 0
        regex = re.compile(pattern, flags)

        if file_pattern:
            files = [Path(f) for f in _glob.glob(str(base / "**" / file_pattern), recursive=True) if Path(f).is_file()]
        elif base.is_file():
            files = [base]
        else:
            files = [p for p in base.rglob("*") if p.is_file() and p.suffix in {".py", ".ts", ".js", ".go", ".rs", ".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".sh", ""}]

        matches = []
        for f in sorted(files)[:100]:
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if regex.search(line):
                        matches.append({"file": str(f), "line": i, "content": line.rstrip()})
                        if len(matches) >= 500:
                            return tool_result(matches=matches, truncated=True)
            except Exception:
                continue
        return tool_result(matches=matches, count=len(matches))
    except Exception as exc:
        return tool_error(str(exc))


# ── Register tools ────────────────────────────────────────────────────────────

registry.register(
    name="read_file",
    description="Read a file with line numbers. Supports offset/limit for pagination.",
    schema={
        "name": "read_file",
        "description": "Read a file with line numbers. Use offset/limit for large files.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative file path"},
                "offset": {"type": "integer", "description": "Start line (1-indexed, default 1)", "default": 1},
                "limit": {"type": "integer", "description": "Max lines to return (default 500)", "default": 500},
            },
            "required": ["path"],
        },
    },
    handler=read_file,
    emoji="📖",
    max_result_chars=200_000,
)

registry.register(
    name="write_file",
    description="Write content to a file, creating parent directories as needed.",
    schema={
        "name": "write_file",
        "description": "Write content to a file. Creates parent directories automatically.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
    },
    handler=write_file,
    emoji="✏️",
)

registry.register(
    name="edit_file",
    description="Replace an exact string in a file. old_string must be unique.",
    schema={
        "name": "edit_file",
        "description": "Replace an exact string in a file. The old_string must appear exactly once.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_string": {"type": "string", "description": "Exact string to find and replace"},
                "new_string": {"type": "string", "description": "Replacement string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    handler=edit_file,
    emoji="🖊️",
)

registry.register(
    name="glob",
    description="Find files matching a glob pattern.",
    schema={
        "name": "glob",
        "description": "Find files matching a glob pattern (e.g. '*.py', '**/*.ts').",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. '*.py')"},
                "path": {"type": "string", "description": "Base directory to search (default '.')"},
            },
            "required": ["pattern"],
        },
    },
    handler=glob_files,
    emoji="🔍",
)

registry.register(
    name="grep",
    description="Search file contents with a regex pattern.",
    schema={
        "name": "grep",
        "description": "Search file contents with a regex. Returns file, line number, and content.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search"},
                "path": {"type": "string", "description": "File or directory to search"},
                "glob": {"type": "string", "description": "Optional: filter files by glob pattern (e.g. '*.py')"},
                "case_insensitive": {"type": "boolean", "description": "Case insensitive search", "default": False},
            },
            "required": ["pattern"],
        },
    },
    handler=grep_files,
    emoji="🔎",
)
