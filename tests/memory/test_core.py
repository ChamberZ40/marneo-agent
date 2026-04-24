# tests/memory/test_core.py
import pytest
from pathlib import Path
from marneo.memory.core import CoreMemory


def test_load_empty_when_no_file(tmp_path):
    cm = CoreMemory(tmp_path / "core.md")
    assert cm.content == ""
    assert cm.as_prompt() == ""


def test_add_and_load(tmp_path):
    cm = CoreMemory(tmp_path / "core.md")
    cm.add("API key 不能提交到 git", source="manual")
    cm2 = CoreMemory(tmp_path / "core.md")
    assert "API key 不能提交到 git" in cm2.content


def test_as_prompt_includes_header(tmp_path):
    cm = CoreMemory(tmp_path / "core.md")
    cm.add("绝对不删生产数据库", source="manual")
    prompt = cm.as_prompt()
    assert "# 核心记忆" in prompt
    assert "绝对不删生产数据库" in prompt


def test_enforces_char_limit(tmp_path):
    cm = CoreMemory(tmp_path / "core.md", max_chars=100)
    cm.add("A" * 200, source="manual")
    assert len(cm.as_prompt()) <= 150  # header + truncation notice


def test_list_entries(tmp_path):
    cm = CoreMemory(tmp_path / "core.md")
    cm.add("rule 1", source="manual")
    cm.add("rule 2", source="llm")
    entries = cm.list_entries()
    assert len(entries) == 2
    assert any("rule 1" in e["content"] for e in entries)
