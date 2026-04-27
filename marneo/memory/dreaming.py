# marneo/memory/dreaming.py
"""AutoDream memory consolidation -- three-phase dreaming sweep.

Openclaw pattern: Light Sleep (ingest) -> REM Sleep (reflect) -> Deep Sleep (score+promote).
Only Deep Sleep writes to core memory. Light and REM accumulate signals.

Scoring formula uses exact openclaw weights with threshold gates.
"""
from __future__ import annotations

import hashlib
import logging
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marneo.memory.core import CoreMemory
from marneo.memory.episodes import EpisodeStore
from marneo.memory.recall_tracker import RecallEntry, RecallTracker

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scoring weights (exact openclaw)
# ---------------------------------------------------------------------------

WEIGHTS = {
    "frequency": 0.24,       # log1p(signal_count) / log1p(10)
    "relevance": 0.30,       # avg retrieval score
    "diversity": 0.15,       # max(unique_queries, recall_days) / 5
    "recency": 0.15,         # exp(-ln2/14 * age_days)  (14-day half-life)
    "consolidation": 0.10,   # multi-day recurrence
    "conceptual": 0.06,      # concept_tags count / 6
}

# Threshold gates -- all must pass for promotion
SCORE_THRESHOLD = 0.75
MIN_RECALL_COUNT = 3
MIN_UNIQUE_QUERIES = 2


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class DreamingReport:
    """Summary of a dreaming sweep execution."""

    light_ingested: int = 0
    rem_themes: list[str] = field(default_factory=list)
    deep_promoted: int = 0
    deep_candidates_scored: int = 0
    deep_scores: list[tuple[str, float]] = field(default_factory=list)  # (key, score)
    duration_ms: int = 0

    def summary(self) -> str:
        lines = [
            f"Light Sleep: {self.light_ingested} episodes ingested",
            f"REM Sleep:   {len(self.rem_themes)} themes identified",
            f"Deep Sleep:  {self.deep_promoted}/{self.deep_candidates_scored} promoted",
            f"Duration:    {self.duration_ms}ms",
        ]
        if self.rem_themes:
            lines.append("Themes:")
            for t in self.rem_themes:
                lines.append(f"  - {t}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# DreamingSweep
# ---------------------------------------------------------------------------

class DreamingSweep:
    """Three-phase memory consolidation: Light -> REM -> Deep.

    Light Sleep: scan recent episodes, deduplicate, record as synthetic recalls.
    REM Sleep:   analyze recall patterns, identify recurring themes (heuristic).
    Deep Sleep:  score all candidates, promote winners to CoreMemory.
    """

    def __init__(self, employee_name: str) -> None:
        self._employee_name = employee_name
        self._tracker = RecallTracker.for_employee(employee_name)
        self._store = EpisodeStore.for_employee(employee_name)
        self._core = CoreMemory.for_employee(employee_name)

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    def run(self) -> DreamingReport:
        """Execute full Light -> REM -> Deep sweep. Returns report."""
        t0 = time.monotonic()
        report = DreamingReport()

        report.light_ingested = self._light_sleep()
        report.rem_themes = self._rem_sleep()
        promoted, scored_count, scores = self._deep_sleep()
        report.deep_promoted = promoted
        report.deep_candidates_scored = scored_count
        report.deep_scores = scores

        report.duration_ms = int((time.monotonic() - t0) * 1000)
        log.info("[Dreaming] Sweep complete: %s", report.summary())
        return report

    # ------------------------------------------------------------------
    # Phase 1: Light Sleep
    # ------------------------------------------------------------------

    def _light_sleep(self) -> int:
        """Ingest recent episodes as synthetic recalls.

        Scans episodes from the last 7 days that are not yet tracked
        in the recall store. Records them with a synthetic score of 0.3
        and a hash of their content as the query, so they enter the
        dreaming pipeline even without organic retrieval hits.
        """
        recent = self._store.list_recent(limit=100)
        now = datetime.now(timezone.utc)
        ingested = 0

        for ep in recent:
            # Skip already-promoted episodes
            if ep.promoted_to_core:
                continue

            # Only ingest episodes from the last 7 days
            try:
                ep_date = datetime.strptime(ep.created_at[:10], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc,
                )
                age_days = (now - ep_date).days
            except (ValueError, TypeError):
                age_days = 999

            if age_days > 7:
                continue

            # Skip if already tracked
            existing = self._tracker.get_entry(ep.id)
            if existing is not None:
                continue

            # Record as synthetic recall (content hash as query for dedup)
            synthetic_query = f"__synthetic__{hashlib.sha256(ep.content.encode()).hexdigest()[:16]}"
            self._tracker.record(
                episode_id=ep.id,
                content=ep.content,
                score=0.3,
                query=synthetic_query,
            )
            ingested += 1

        log.debug("[Dreaming] Light Sleep: ingested %d episodes", ingested)
        return ingested

    # ------------------------------------------------------------------
    # Phase 2: REM Sleep
    # ------------------------------------------------------------------

    def _rem_sleep(self) -> list[str]:
        """Analyze recall patterns, identify recurring themes.

        Simple heuristic (no LLM): count concept tags across all
        non-promoted entries, surface the top clusters.
        """
        candidates = self._tracker.get_candidates()
        if not candidates:
            return []

        # Collect concept tag frequencies across all candidates
        tag_counter: Counter[str] = Counter()
        for entry in candidates:
            for tag in entry.concept_tags:
                tag_counter[tag] += 1

        # Themes = tags that appear in multiple entries (>= 2)
        themes: list[str] = []
        for tag, count in tag_counter.most_common(10):
            if count >= 2:
                themes.append(f"{tag} (x{count})")

        log.debug("[Dreaming] REM Sleep: %d themes from %d candidates",
                  len(themes), len(candidates))
        return themes

    # ------------------------------------------------------------------
    # Phase 3: Deep Sleep
    # ------------------------------------------------------------------

    def _deep_sleep(self) -> tuple[int, int, list[tuple[str, float]]]:
        """Score + promote. Returns (promoted_count, candidates_count, scores)."""
        candidates = self._tracker.get_candidates()
        if not candidates:
            return 0, 0, []

        scored: list[tuple[float, RecallEntry]] = []
        all_scores: list[tuple[str, float]] = []

        for entry in candidates:
            score = self.score_candidate(entry)
            scored.append((score, entry))
            all_scores.append((entry.key, score))

        scored.sort(key=lambda x: x[0], reverse=True)
        all_scores.sort(key=lambda x: x[1], reverse=True)

        promoted = 0
        for score, entry in scored:
            # Threshold gates: all must pass
            if score < SCORE_THRESHOLD:
                continue
            if entry.recall_count < MIN_RECALL_COUNT:
                continue
            if len(entry.query_hashes) < MIN_UNIQUE_QUERIES:
                continue

            # Check core memory budget
            current_content = self._core.content
            if len(current_content) + len(entry.content) >= self._core._max_chars:
                log.debug("[Dreaming] Core memory budget full, stopping promotion")
                break

            # Promote to core memory
            self._core.add(entry.content, source="dream")
            self._tracker.mark_promoted(entry.key)

            # Also mark in episode store if possible
            try:
                self._store.mark_promoted(entry.key)
            except Exception:
                pass

            promoted += 1
            log.info(
                "[Dreaming] Promoted %s (score=%.3f, recalls=%d): %s",
                entry.key, score, entry.recall_count, entry.content[:60],
            )

        return promoted, len(candidates), all_scores

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_candidate(self, entry: RecallEntry) -> float:
        """Compute weighted score using openclaw formula.

        Components:
          frequency     0.24  log1p(recall_count) / log1p(10)
          relevance     0.30  avg retrieval score (total_score / recall_count)
          diversity     0.15  max(unique_queries, recall_days) / 5
          recency       0.15  exp(-ln2/14 * age_days)  -- 14-day half-life
          consolidation 0.10  multi-day recurrence ratio
          conceptual    0.06  concept_tags count / 6
        """
        # Frequency: log-scaled recall count
        frequency = math.log1p(entry.recall_count) / math.log1p(10)

        # Relevance: average retrieval score, clamped to [0, 1]
        if entry.recall_count > 0:
            relevance = min(entry.total_score / entry.recall_count, 1.0)
        else:
            relevance = 0.0

        # Diversity: max of unique query count and distinct recall days
        unique_queries = len(entry.query_hashes)
        unique_days = len(entry.recall_days)
        diversity = min(max(unique_queries, unique_days) / 5.0, 1.0)

        # Recency: exponential decay with 14-day half-life
        age_days = self._compute_age_days(entry.last_recalled_at)
        ln2 = math.log(2)
        recency = math.exp(-ln2 / 14.0 * age_days)

        # Consolidation: fraction of recall days vs total age span
        if len(entry.recall_days) >= 2:
            try:
                days_sorted = sorted(entry.recall_days)
                first = datetime.strptime(days_sorted[0], "%Y-%m-%d")
                last = datetime.strptime(days_sorted[-1], "%Y-%m-%d")
                span = max((last - first).days, 1)
                consolidation = min(len(entry.recall_days) / span, 1.0)
            except (ValueError, TypeError):
                consolidation = 0.0
        else:
            consolidation = 0.0

        # Conceptual: tag richness
        conceptual = min(len(entry.concept_tags) / 6.0, 1.0)

        # Weighted sum
        score = (
            WEIGHTS["frequency"] * frequency
            + WEIGHTS["relevance"] * relevance
            + WEIGHTS["diversity"] * diversity
            + WEIGHTS["recency"] * recency
            + WEIGHTS["consolidation"] * consolidation
            + WEIGHTS["conceptual"] * conceptual
        )

        return score

    @staticmethod
    def _compute_age_days(iso_timestamp: str) -> float:
        """Compute age in days from an ISO timestamp to now."""
        if not iso_timestamp:
            return 30.0  # default to 30 days for missing timestamps
        try:
            dt = datetime.fromisoformat(iso_timestamp)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return max((now - dt).total_seconds() / 86400.0, 0.0)
        except (ValueError, TypeError):
            return 30.0

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def for_employee(cls, employee_name: str) -> "DreamingSweep":
        return cls(employee_name)
