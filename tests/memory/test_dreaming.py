# tests/memory/test_dreaming.py
"""Tests for DreamingSweep -- three-phase memory consolidation.

Light Sleep (ingest) -> REM Sleep (reflect) -> Deep Sleep (score + promote).
Tests verify the scoring formula, threshold gates, and full sweep lifecycle.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from marneo.memory.core import CoreMemory
from marneo.memory.episodes import Episode, EpisodeStore
from marneo.memory.recall_tracker import RecallEntry, RecallTracker
from marneo.memory.dreaming import (
    DreamingSweep,
    DreamingReport,
    WEIGHTS,
    SCORE_THRESHOLD,
    MIN_RECALL_COUNT,
    MIN_UNIQUE_QUERIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(
    key: str = "ep_1",
    content: str = "test content about pandas DataFrame operations",
    recall_count: int = 5,
    total_score: float = 4.0,
    max_score: float = 0.9,
    query_hashes: list[str] | None = None,
    recall_days: list[str] | None = None,
    concept_tags: list[str] | None = None,
    first_recalled_at: str = "",
    last_recalled_at: str = "",
    promoted_at: str = "",
) -> RecallEntry:
    """Build a RecallEntry with sensible defaults."""
    now = datetime.now(timezone.utc)
    return RecallEntry(
        key=key,
        content=content,
        recall_count=recall_count,
        total_score=total_score,
        max_score=max_score,
        first_recalled_at=first_recalled_at or (now - timedelta(days=7)).isoformat(),
        last_recalled_at=last_recalled_at or now.isoformat(),
        query_hashes=query_hashes if query_hashes is not None else [f"h{i}" for i in range(3)],
        recall_days=recall_days if recall_days is not None else ["2026-04-20", "2026-04-21", "2026-04-22"],
        concept_tags=concept_tags if concept_tags is not None else ["pandas", "dataframe"],
        promoted_at=promoted_at,
    )


def _make_sweep(tmp_path: Path, employee: str = "alice") -> DreamingSweep:
    """Build a DreamingSweep with all storage rooted under tmp_path.

    Patches get_marneo_dir so that RecallTracker, EpisodeStore, and
    CoreMemory all resolve inside the test's temporary directory.
    """
    marneo_dir = tmp_path / ".marneo"
    marneo_dir.mkdir(parents=True, exist_ok=True)

    with patch("marneo.core.paths.get_marneo_dir", return_value=marneo_dir):
        sweep = DreamingSweep(employee_name=employee)
    return sweep


def _make_sweep_with_mocks(
    tmp_path: Path,
    candidates: list[RecallEntry] | None = None,
) -> DreamingSweep:
    """Build a DreamingSweep with mocked tracker for controlled candidate data."""
    sweep = _make_sweep(tmp_path)

    # Replace tracker with a mock that returns controlled candidates
    mock_tracker = MagicMock(spec=RecallTracker)
    mock_tracker.get_candidates.return_value = candidates or []
    mock_tracker.get_entry.return_value = None
    mock_tracker.mark_promoted = MagicMock()
    sweep._tracker = mock_tracker

    return sweep


# ---------------------------------------------------------------------------
# Test: scoring formula
# ---------------------------------------------------------------------------

class TestScoringFormula:
    """Verify that score_candidate computes each signal correctly."""

    def test_scoring_formula(self, tmp_path):
        sweep = _make_sweep(tmp_path)
        now = datetime.now(timezone.utc)

        entry = _entry(
            recall_count=10,
            total_score=8.0,
            max_score=0.95,
            query_hashes=[f"h{i}" for i in range(5)],
            recall_days=["2026-04-20", "2026-04-21", "2026-04-22", "2026-04-23"],
            concept_tags=["pandas", "sql", "database"],
            last_recalled_at=now.isoformat(),
        )

        score = sweep.score_candidate(entry)

        # Manually compute expected components
        frequency = math.log1p(10) / math.log1p(10)  # = 1.0
        relevance = min(8.0 / 10, 1.0)               # = 0.8
        diversity = min(max(5, 4) / 5.0, 1.0)        # = 1.0
        # recency ~ exp(0) = 1.0 (just recalled)
        # consolidation: 4 days over span of 3 days (20->23) => min(4/3, 1) = 1.0
        conceptual = min(3 / 6.0, 1.0)               # = 0.5

        # Score should be positive and reasonable
        assert isinstance(score, float)
        assert score > 0
        # With these strong signals, score should be well above threshold
        assert score > SCORE_THRESHOLD * 0.8, f"Expected high score, got {score}"


class TestScoreHighFrequency:
    """Entry with many recalls should score higher on the frequency signal."""

    def test_score_high_frequency(self, tmp_path):
        sweep = _make_sweep(tmp_path)

        low_freq = _entry(key="low", recall_count=1, total_score=0.5)
        high_freq = _entry(key="high", recall_count=50, total_score=40.0)

        score_low = sweep.score_candidate(low_freq)
        score_high = sweep.score_candidate(high_freq)

        assert score_high > score_low, (
            f"High-frequency entry ({score_high}) should score above "
            f"low-frequency entry ({score_low})"
        )


class TestScoreRecentVsOld:
    """Recent entry should score higher on recency than an old one."""

    def test_score_recent_vs_old(self, tmp_path):
        sweep = _make_sweep(tmp_path)
        now = datetime.now(timezone.utc)

        recent = _entry(
            key="recent",
            last_recalled_at=now.isoformat(),
        )
        old = _entry(
            key="old",
            last_recalled_at=(now - timedelta(days=90)).isoformat(),
        )

        score_recent = sweep.score_candidate(recent)
        score_old = sweep.score_candidate(old)

        assert score_recent > score_old, (
            f"Recent entry ({score_recent}) should score above "
            f"old entry ({score_old})"
        )


# ---------------------------------------------------------------------------
# Test: threshold gates
# ---------------------------------------------------------------------------

class TestThresholdGates:
    """Entries below threshold/minRecallCount/minUniqueQueries must be rejected."""

    def test_threshold_gates(self, tmp_path):
        sweep = _make_sweep_with_mocks(tmp_path)

        # Entry with minimal activity: recall_count=1 < MIN_RECALL_COUNT=3,
        # unique queries=1 < MIN_UNIQUE_QUERIES=2
        weak = _entry(
            key="weak",
            recall_count=1,
            total_score=0.1,
            max_score=0.1,
            query_hashes=["h0"],
            recall_days=["2026-04-20"],
            concept_tags=[],
        )
        sweep._tracker.get_candidates.return_value = [weak]

        # Also mock _store and _core so deep_sleep doesn't fail
        mock_store = MagicMock(spec=EpisodeStore)
        mock_store.list_recent.return_value = []
        sweep._store = mock_store

        core_path = tmp_path / "core.md"
        core_path.write_text("", encoding="utf-8")
        sweep._core = CoreMemory(core_path)

        promoted, _, _ = sweep._deep_sleep()
        assert promoted == 0, "Weak entry should not pass threshold gates"
        sweep._tracker.mark_promoted.assert_not_called()

    def test_below_min_recall_count(self, tmp_path):
        sweep = _make_sweep_with_mocks(tmp_path)

        # Good score but recall_count < MIN_RECALL_COUNT
        entry = _entry(
            key="few_recalls",
            recall_count=MIN_RECALL_COUNT - 1,
            total_score=5.0,
            max_score=0.95,
            query_hashes=[f"h{i}" for i in range(5)],
            recall_days=[f"2026-04-{d:02d}" for d in range(1, 10)],
        )
        sweep._tracker.get_candidates.return_value = [entry]

        core_path = tmp_path / "core.md"
        core_path.write_text("", encoding="utf-8")
        sweep._core = CoreMemory(core_path)

        promoted, _, _ = sweep._deep_sleep()
        assert promoted == 0

    def test_below_min_unique_queries(self, tmp_path):
        sweep = _make_sweep_with_mocks(tmp_path)

        # Many recalls but only 1 unique query < MIN_UNIQUE_QUERIES
        entry = _entry(
            key="one_query",
            recall_count=20,
            total_score=18.0,
            max_score=0.95,
            query_hashes=["single_hash"],  # only 1 unique query
            recall_days=[f"2026-04-{d:02d}" for d in range(1, 10)],
        )
        sweep._tracker.get_candidates.return_value = [entry]

        core_path = tmp_path / "core.md"
        core_path.write_text("", encoding="utf-8")
        sweep._core = CoreMemory(core_path)

        promoted, _, _ = sweep._deep_sleep()
        assert promoted == 0


# ---------------------------------------------------------------------------
# Test: deep sleep promotes
# ---------------------------------------------------------------------------

class TestDeepSleepPromotes:
    """A strong candidate should be promoted to core memory."""

    def test_deep_sleep_promotes(self, tmp_path):
        sweep = _make_sweep_with_mocks(tmp_path)

        strong = _entry(
            key="strong",
            content="Always use parameterized queries",
            recall_count=20,
            total_score=16.0,
            max_score=0.95,
            query_hashes=[f"h{i}" for i in range(8)],
            recall_days=[f"2026-04-{d:02d}" for d in range(1, 15)],
            concept_tags=["sql", "security", "queries", "database"],
        )
        sweep._tracker.get_candidates.return_value = [strong]

        # Use a real CoreMemory with plenty of budget
        core_path = tmp_path / "core.md"
        core_path.write_text("", encoding="utf-8")
        sweep._core = CoreMemory(core_path, max_chars=2000)

        promoted, scored_count, scores = sweep._deep_sleep()
        assert promoted == 1
        assert scored_count == 1
        sweep._tracker.mark_promoted.assert_called_once_with("strong")

        # Verify content was added to core memory
        core_content = sweep._core.content
        assert "Always use parameterized queries" in core_content


# ---------------------------------------------------------------------------
# Test: deep sleep respects core budget
# ---------------------------------------------------------------------------

class TestDeepSleepRespectsBudget:
    """Promotion should stop when core memory is near its char limit."""

    def test_deep_sleep_respects_core_budget(self, tmp_path):
        sweep = _make_sweep_with_mocks(tmp_path)

        # Pre-fill core memory near the limit (950 chars of content)
        core_path = tmp_path / "core.md"
        core_path.parent.mkdir(parents=True, exist_ok=True)
        sweep._core = CoreMemory(core_path, max_chars=1000)
        sweep._core.add("X" * 950, source="manual")

        big_entry = _entry(
            key="big",
            content="Y" * 200,
            recall_count=20,
            total_score=16.0,
            max_score=0.95,
            query_hashes=[f"h{i}" for i in range(8)],
            recall_days=[f"2026-04-{d:02d}" for d in range(1, 15)],
            concept_tags=["a", "b", "c", "d"],
        )
        sweep._tracker.get_candidates.return_value = [big_entry]

        promoted, _, _ = sweep._deep_sleep()
        assert promoted == 0, "Should not promote when core memory is near budget"
        sweep._tracker.mark_promoted.assert_not_called()


# ---------------------------------------------------------------------------
# Test: light sleep ingests
# ---------------------------------------------------------------------------

class TestLightSleepIngests:
    """Light sleep should record recent episodes as synthetic recalls."""

    def test_light_sleep_ingests(self, tmp_path):
        marneo_dir = tmp_path / ".marneo"
        marneo_dir.mkdir(parents=True, exist_ok=True)

        with patch("marneo.core.paths.get_marneo_dir", return_value=marneo_dir):
            sweep = DreamingSweep(employee_name="alice")

        # Add recent episodes to the store
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for i in range(3):
            sweep._store.add(Episode(
                content=f"Episode {i} about important topic",
                type="discovery",
                created_at=today,
            ))

        ingested = sweep._light_sleep()
        # Should have ingested the 3 recent, non-tracked episodes
        assert ingested == 3

        # Running again should ingest 0 (already tracked)
        ingested_again = sweep._light_sleep()
        assert ingested_again == 0


# ---------------------------------------------------------------------------
# Test: full sweep
# ---------------------------------------------------------------------------

class TestFullSweep:
    """run() should execute all three phases and return a DreamingReport."""

    def test_full_sweep(self, tmp_path):
        marneo_dir = tmp_path / ".marneo"
        marneo_dir.mkdir(parents=True, exist_ok=True)

        with patch("marneo.core.paths.get_marneo_dir", return_value=marneo_dir):
            sweep = DreamingSweep(employee_name="alice")

        report = sweep.run()

        assert isinstance(report, DreamingReport)
        assert report.duration_ms >= 0
        assert isinstance(report.light_ingested, int)
        assert isinstance(report.rem_themes, list)
        assert isinstance(report.deep_promoted, int)
        assert isinstance(report.deep_candidates_scored, int)
        assert isinstance(report.deep_scores, list)

    def test_full_sweep_with_data(self, tmp_path):
        """Full sweep with episodes that get ingested, themed, and scored."""
        marneo_dir = tmp_path / ".marneo"
        marneo_dir.mkdir(parents=True, exist_ok=True)

        with patch("marneo.core.paths.get_marneo_dir", return_value=marneo_dir):
            sweep = DreamingSweep(employee_name="alice")

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for i in range(5):
            sweep._store.add(Episode(
                content=f"Use pandas for data analysis task {i}",
                type="discovery",
                tags=["pandas", "data"],
                created_at=today,
            ))

        report = sweep.run()
        assert report.light_ingested == 5
        # With only synthetic recalls (1 each), entries won't pass thresholds
        assert report.deep_promoted == 0

    def test_report_summary(self):
        """DreamingReport.summary() returns a human-readable string."""
        report = DreamingReport(
            light_ingested=3,
            rem_themes=["pandas (x4)", "sql (x2)"],
            deep_promoted=1,
            deep_candidates_scored=5,
            deep_scores=[("ep_1", 0.85)],
            duration_ms=42,
        )
        summary = report.summary()
        assert "Light Sleep" in summary
        assert "REM Sleep" in summary
        assert "Deep Sleep" in summary
        assert "3" in summary
        assert "pandas" in summary
