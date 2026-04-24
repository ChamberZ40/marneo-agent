# tests/memory/test_retriever.py
import pytest
from pathlib import Path
from marneo.memory.episodes import EpisodeStore, Episode
from marneo.memory.retriever import HybridRetriever


@pytest.fixture
def store_with_episodes(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    store.add(Episode(id="ep1", content="Python pandas 处理 UTF-8 编码问题", type="discovery", tags=["pandas"]))
    store.add(Episode(id="ep2", content="Git 提交前必须检查 API key 泄露", type="preference", tags=["git"]))
    store.add(Episode(id="ep3", content="飞书 Bitable 多维表格创建记录方法", type="advice", tags=["feishu"]))
    store.add(Episode(id="ep4", content="Docker 部署时需要设置环境变量", type="decision", tags=["docker"]))
    return store


def test_retrieve_bm25_only(store_with_episodes, tmp_path):
    """BM25-only retrieval works without vector index."""
    retriever = HybridRetriever(store_with_episodes, tmp_path / "v.npy")
    results = retriever.retrieve_bm25("pandas 编码", n=2)
    assert len(results) > 0
    assert any("pandas" in r.content for r in results)


def test_retrieve_returns_at_most_n(store_with_episodes, tmp_path):
    retriever = HybridRetriever(store_with_episodes, tmp_path / "v.npy")
    retriever.rebuild_index()
    results = retriever.retrieve("任何问题", n=2)
    assert len(results) <= 2


def test_retrieve_empty_store(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    retriever = HybridRetriever(store, tmp_path / "v.npy")
    retriever.rebuild_index()
    results = retriever.retrieve("pandas", n=3)
    assert results == []


def test_rebuild_index_no_crash(store_with_episodes, tmp_path):
    """rebuild_index() should not crash even if fastembed unavailable."""
    retriever = HybridRetriever(store_with_episodes, tmp_path / "v.npy")
    retriever.rebuild_index()  # may or may not have vectors
    assert retriever._bm25 is not None
