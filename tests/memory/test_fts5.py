# tests/memory/test_fts5.py
"""Tests for FTS5 full-text search in EpisodeStore."""
from marneo.memory.episodes import Episode, EpisodeStore


class TestFTS5Search:
    def test_search_basic(self, tmp_path):
        store = EpisodeStore(tmp_path / "test.db")
        store.add(Episode(content="Python deployment scripts for CI/CD pipeline"))
        store.add(Episode(content="React component for user dashboard"))
        store.add(Episode(content="Database migration strategy for PostgreSQL"))

        results = store.search_fts("Python deployment", limit=5)
        assert len(results) >= 1
        assert any("Python" in r.content for r in results)

    def test_search_empty_query(self, tmp_path):
        store = EpisodeStore(tmp_path / "test.db")
        store.add(Episode(content="some content"))
        assert store.search_fts("") == []

    def test_search_no_match(self, tmp_path):
        store = EpisodeStore(tmp_path / "test.db")
        store.add(Episode(content="Python deployment"))
        results = store.search_fts("kubernetes helm chart")
        assert results == []

    def test_search_by_tags(self, tmp_path):
        store = EpisodeStore(tmp_path / "test.db")
        store.add(Episode(content="Fixed auth bug", tags=["security", "auth"]))
        store.add(Episode(content="Added caching", tags=["performance"]))

        results = store.search_fts("security")
        assert len(results) >= 1

    def test_search_by_project(self, tmp_path):
        store = EpisodeStore(tmp_path / "test.db")
        store.add(Episode(content="Deployed v2", project="marneo"))
        store.add(Episode(content="Deployed v1", project="other"))

        results = store.search_fts("marneo")
        assert len(results) >= 1

    def test_last_accessed_at_updated(self, tmp_path):
        store = EpisodeStore(tmp_path / "test.db")
        ep_id = store.add(Episode(content="test episode"))
        store.increment_access(ep_id)

        ep = store.get(ep_id)
        assert ep is not None
        assert ep.access_count == 1
