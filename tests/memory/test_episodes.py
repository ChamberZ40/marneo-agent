# tests/memory/test_episodes.py
import pytest
from pathlib import Path
from marneo.memory.episodes import EpisodeStore, Episode


def test_add_and_get(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    ep = Episode(content="用 pd.read_csv(encoding='utf-8-sig') 处理飞书导出", type="discovery", tags=["pandas", "feishu"])
    ep_id = store.add(ep)
    assert ep_id.startswith("ep_")
    result = store.get(ep_id)
    assert result is not None
    assert result.content == ep.content


def test_list_recent(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    store.add(Episode(content="fact 1", type="decision"))
    store.add(Episode(content="fact 2", type="preference"))
    store.add(Episode(content="fact 3", type="advice"))
    recent = store.list_recent(limit=2)
    assert len(recent) == 2


def test_increment_access(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    ep_id = store.add(Episode(content="test", type="general"))
    store.increment_access(ep_id)
    store.increment_access(ep_id)
    ep = store.get(ep_id)
    assert ep.access_count == 2


def test_get_promotion_candidates(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    ep_id = store.add(Episode(content="frequently used", type="preference"))
    for _ in range(5):
        store.increment_access(ep_id)
    candidates = store.get_promotion_candidates(min_access=5)
    assert any(c.id == ep_id for c in candidates)


def test_mark_promoted(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    ep_id = store.add(Episode(content="x", type="general"))
    store.mark_promoted(ep_id)
    ep = store.get(ep_id)
    assert ep.promoted_to_core is True


def test_count(tmp_path):
    store = EpisodeStore(tmp_path / "episodes.db")
    store.add(Episode(content="a", type="general"))
    store.add(Episode(content="b", type="general"))
    assert store.count() == 2
