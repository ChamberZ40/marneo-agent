# tests/memory/test_recall_tracker.py
"""Tests for RecallTracker + RecallEntry — the retrieval-hit tracker
that feeds the dreaming promotion pipeline."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from marneo.memory.recall_tracker import RecallEntry, RecallTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(tmp_path, name: str = "alice") -> RecallTracker:
    """Build a RecallTracker whose resolve_path lands inside tmp_path."""
    dreams_dir = tmp_path / "employees" / name / "memory" / ".dreams"
    dreams_dir.mkdir(parents=True, exist_ok=True)

    def _fake_resolve(employee_name: str):
        return dreams_dir / "recall.json"

    with patch.object(RecallTracker, "_resolve_path", staticmethod(_fake_resolve)):
        return RecallTracker(name)


# ---------------------------------------------------------------------------
# Tests: record basics
# ---------------------------------------------------------------------------

class TestRecordBasic:
    """test_record_basic: record a hit, verify entry created."""

    def test_record_basic(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.record("ep_001", "some episode content", score=0.85, query="how to deploy")

        entry = tracker.get_entry("ep_001")
        assert entry is not None
        assert entry.key == "ep_001"
        assert entry.recall_count == 1
        assert entry.total_score == pytest.approx(0.85)
        assert entry.max_score == pytest.approx(0.85)
        assert entry.first_recalled_at != ""
        assert entry.last_recalled_at != ""
        assert tracker.entry_count == 1


class TestRecordIncrements:
    """test_record_increments: multiple records for same key increment counts."""

    def test_record_increments(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.record("ep_002", "content A", score=0.5, query="query A")
        tracker.record("ep_002", "content A", score=0.7, query="query A")
        tracker.record("ep_002", "content A", score=0.9, query="query A")

        entry = tracker.get_entry("ep_002")
        assert entry.recall_count == 3
        assert entry.total_score == pytest.approx(0.5 + 0.7 + 0.9)
        assert entry.max_score == pytest.approx(0.9)


class TestRecordTracksUniqueQueries:
    """test_record_tracks_unique_queries: different queries produce different hashes."""

    def test_record_tracks_unique_queries(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.record("ep_003", "content", score=0.5, query="alpha")
        tracker.record("ep_003", "content", score=0.5, query="beta")
        tracker.record("ep_003", "content", score=0.5, query="gamma")
        # duplicate query should NOT add a new hash
        tracker.record("ep_003", "content", score=0.5, query="alpha")

        entry = tracker.get_entry("ep_003")
        assert len(entry.query_hashes) == 3
        expected_hashes = {
            hashlib.sha256(q.encode()).hexdigest()
            for q in ("alpha", "beta", "gamma")
        }
        assert set(entry.query_hashes) == expected_hashes


class TestRecordTracksRecallDays:
    """test_record_tracks_recall_days: records on different days tracked."""

    def test_record_tracks_recall_days(self, tmp_path):
        tracker = _make_tracker(tmp_path)

        day1 = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
        day2 = datetime(2026, 4, 2, 14, 0, 0, tzinfo=timezone.utc)
        day3 = datetime(2026, 4, 2, 15, 0, 0, tzinfo=timezone.utc)  # same day as day2

        with patch("marneo.memory.recall_tracker.datetime") as mock_dt:
            mock_dt.now.return_value = day1
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            tracker.record("ep_004", "content", score=0.5, query="q1")

            mock_dt.now.return_value = day2
            tracker.record("ep_004", "content", score=0.5, query="q2")

            mock_dt.now.return_value = day3
            tracker.record("ep_004", "content", score=0.5, query="q3")

        entry = tracker.get_entry("ep_004")
        # day2 and day3 are the same date, so expect 2 distinct days
        assert len(entry.recall_days) == 2


class TestGetCandidatesExcludesPromoted:
    """test_get_candidates_excludes_promoted: promoted entries not returned."""

    def test_get_candidates_excludes_promoted(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.record("ep_ok", "keep me", score=0.5, query="q")
        tracker.record("ep_promoted", "already promoted", score=0.5, query="q")
        tracker.mark_promoted("ep_promoted")

        candidates = tracker.get_candidates()
        keys = [c.key for c in candidates]
        assert "ep_ok" in keys
        assert "ep_promoted" not in keys


class TestMarkPromoted:
    """test_mark_promoted: mark and verify excluded."""

    def test_mark_promoted(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.record("ep_010", "content", score=0.8, query="query")

        # before promotion
        entry = tracker.get_entry("ep_010")
        assert entry.promoted_at == ""

        tracker.mark_promoted("ep_010")
        entry = tracker.get_entry("ep_010")
        assert entry.promoted_at != ""
        # promoted entries excluded from candidates
        candidates = tracker.get_candidates()
        assert all(c.key != "ep_010" for c in candidates)

    def test_mark_promoted_nonexistent_is_noop(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        # should not raise
        tracker.mark_promoted("does_not_exist")


class TestConceptExtraction:
    """test_concept_extraction: verify concept tags are extracted."""

    def test_concept_extraction(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        text = "Use pandas DataFrame with SQLAlchemy engine for database queries"
        tracker.record("ep_concepts", text, score=0.9, query="data")

        entry = tracker.get_entry("ep_concepts")
        assert len(entry.concept_tags) > 0
        assert len(entry.concept_tags) <= 8
        # Should contain meaningful tokens, not stopwords
        lowered = [t.lower() for t in entry.concept_tags]
        assert "pandas" in lowered or "dataframe" in lowered
        # Stopwords should be excluded
        for tag in entry.concept_tags:
            assert tag.lower() not in {"the", "and", "for", "with"}

    def test_concept_extraction_max_eight(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        # Long text with many distinct words
        text = " ".join(f"concept{i}" for i in range(20))
        tracker.record("ep_many", text, score=0.5, query="q")
        entry = tracker.get_entry("ep_many")
        assert len(entry.concept_tags) <= 8


class TestPersistence:
    """test_persistence: write, reload from disk, verify data intact."""

    def test_persistence(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.record("ep_persist", "important fact", score=0.75, query="memory lookup")
        tracker.record("ep_persist", "important fact", score=0.80, query="another lookup")

        # Verify the JSON file was written
        recall_json = tmp_path / "employees" / "alice" / "memory" / ".dreams" / "recall.json"
        assert recall_json.exists()

        # Create a new tracker instance to force reload from disk
        tracker2 = _make_tracker(tmp_path, name="alice")
        entry = tracker2.get_entry("ep_persist")
        assert entry is not None
        assert entry.recall_count == 2
        assert entry.total_score == pytest.approx(0.75 + 0.80)
        assert entry.max_score == pytest.approx(0.80)
        assert len(entry.query_hashes) == 2
        assert len(entry.concept_tags) > 0

    def test_persistence_json_valid(self, tmp_path):
        """The stored JSON should be parseable and contain expected keys."""
        tracker = _make_tracker(tmp_path)
        tracker.record("ep_json", "test data", score=0.5, query="q")

        recall_json = tmp_path / "employees" / "alice" / "memory" / ".dreams" / "recall.json"
        data = json.loads(recall_json.read_text(encoding="utf-8"))
        assert "ep_json" in data
        assert data["ep_json"]["recall_count"] == 1
        assert data["ep_json"]["key"] == "ep_json"
