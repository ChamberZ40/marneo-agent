# tests/tools/test_memory_tools.py
import json
import pytest
from marneo.tools.core.memory_tools import recall_memory, get_skill, add_core_memory


def test_recall_memory_empty(tmp_path):
    from marneo.memory.episodes import EpisodeStore
    from marneo.memory.retriever import HybridRetriever
    store = EpisodeStore(tmp_path / "ep.db")
    retriever = HybridRetriever(store, tmp_path / "v.npy")
    retriever.rebuild_index()
    result = json.loads(recall_memory({"query": "pandas"}, _retriever=retriever))
    assert result["results"] == []


def test_recall_memory_no_retriever():
    result = json.loads(recall_memory({"query": "pandas"}))
    assert "results" in result  # returns empty gracefully


def test_add_core_memory_writes(tmp_path):
    from marneo.memory.core import CoreMemory
    cm = CoreMemory(tmp_path / "core.md")
    result = json.loads(add_core_memory(
        {"content": "绝对不删除生产数据", "reason": "测试"},
        _core_memory=cm,
    ))
    assert result["ok"] is True
    assert "绝对不删除生产数据" in cm.content


def test_get_skill_not_found():
    result = json.loads(get_skill({"skill_id": "nonexistent-xyz-abc-123"}))
    assert "error" in result


def test_recall_memory_missing_query():
    result = json.loads(recall_memory({}))
    assert "error" in result
