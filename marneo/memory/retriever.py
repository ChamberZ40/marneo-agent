# marneo/memory/retriever.py
"""Hybrid BM25 + fastembed retriever for episodic memory.

Pattern from mempalace: vector search is the floor, BM25 re-ranks candidates.
Falls back to BM25-only when fastembed model not available.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
from rank_bm25 import BM25Okapi

from marneo.memory.episodes import Episode, EpisodeStore

log = logging.getLogger(__name__)

_EMBED_MODEL = "BAAI/bge-small-zh-v1.5"  # ~50MB, Chinese + English, no GPU


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: split on whitespace + CJK chars."""
    import re
    tokens = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower())
    return tokens or [text]


class HybridRetriever:
    """BM25 + fastembed vector hybrid retrieval."""

    def __init__(self, store: EpisodeStore, vectors_path: Path) -> None:
        self._store = store
        self._vectors_path = vectors_path
        self._episodes: list[Episode] = []
        self._bm25: Optional[BM25Okapi] = None
        self._vectors: Optional[np.ndarray] = None
        self._embedder: Any = None

    def _get_embedder(self) -> Any:
        if self._embedder is None:
            try:
                from fastembed import TextEmbedding
                self._embedder = TextEmbedding(model_name=_EMBED_MODEL)
                log.info("[Memory] fastembed model loaded: %s", _EMBED_MODEL)
            except Exception as e:
                log.warning("[Memory] fastembed not available: %s", e)
        return self._embedder

    def rebuild_index(self) -> None:
        """Load all non-promoted episodes and build BM25 + vector index."""
        all_eps = self._store.get_all()
        self._episodes = [e for e in all_eps if not e.promoted_to_core]

        if not self._episodes:
            self._bm25 = None
            self._vectors = None
            return

        tokenized = [_tokenize(e.content) for e in self._episodes]
        self._bm25 = BM25Okapi(tokenized)

        embedder = self._get_embedder()
        if embedder is not None:
            try:
                texts = [e.content for e in self._episodes]
                vecs = list(embedder.embed(texts))
                arr = np.array(vecs, dtype=np.float32)
                norms = np.linalg.norm(arr, axis=1, keepdims=True)
                norms = np.where(norms == 0, 1, norms)
                self._vectors = arr / norms
                self._vectors_path.parent.mkdir(parents=True, exist_ok=True)
                np.save(str(self._vectors_path), self._vectors)
            except Exception as e:
                log.warning("[Memory] Vector build failed: %s", e)
                self._vectors = None

    def retrieve(self, query: str, n: int = 3, threshold: float = 0.0) -> list[Episode]:
        """Hybrid retrieve: vector floor + BM25 rerank."""
        if not self._episodes:
            return []

        if self._bm25 is None:
            self.rebuild_index()
        if not self._episodes:
            return []

        embedder = self._get_embedder()
        if embedder is not None and self._vectors is not None:
            try:
                q_vec = np.array(list(embedder.embed([query]))[0], dtype=np.float32)
                q_norm = np.linalg.norm(q_vec)
                if q_norm > 0:
                    q_vec = q_vec / q_norm
                scores = self._vectors @ q_vec
                top_k = min(n * 3, len(self._episodes))
                top_idx = np.argsort(scores)[::-1][:top_k].tolist()
                candidates = [self._episodes[i] for i in top_idx]
                candidate_scores = {self._episodes[i].id: float(scores[i]) for i in top_idx}
            except Exception as e:
                log.warning("[Memory] Vector retrieval failed: %s", e)
                candidates = self._episodes
                candidate_scores = {}
        else:
            candidates = self._episodes
            candidate_scores = {}

        if self._bm25 and candidates:
            q_tokens = _tokenize(query)
            all_bm25 = self._bm25.get_scores(q_tokens)
            max_bm25 = float(max(all_bm25)) if len(all_bm25) > 0 else 1.0
            combined: list[tuple[float, Episode]] = []
            for ep in candidates:
                idx = next((i for i, e in enumerate(self._episodes) if e.id == ep.id), -1)
                if idx == -1:
                    continue
                bm25_score = float(all_bm25[idx]) / (max_bm25 + 1e-8)
                vec_score = candidate_scores.get(ep.id, 0.0)
                final_score = 0.6 * vec_score + 0.4 * bm25_score
                combined.append((final_score, ep))
            combined.sort(key=lambda x: x[0], reverse=True)
            results = [ep for score, ep in combined if score >= threshold][:n]
        else:
            results = candidates[:n]

        for ep in results:
            self._store.increment_access(ep.id)

        return results

    def retrieve_bm25(self, query: str, n: int = 3) -> list[Episode]:
        """BM25-only retrieval (fallback when vectors not available)."""
        if not self._episodes:
            self.rebuild_index()
        if not self._episodes:
            return []
        if self._bm25 is None:
            tokenized = [_tokenize(e.content) for e in self._episodes]
            self._bm25 = BM25Okapi(tokenized)
        q_tokens = _tokenize(query)
        scores = self._bm25.get_scores(q_tokens)
        top_idx = np.argsort(scores)[::-1][:n].tolist()
        return [self._episodes[i] for i in top_idx if scores[i] > 0]

    @classmethod
    def for_employee(cls, employee_name: str) -> "HybridRetriever":
        from marneo.core.paths import get_marneo_dir
        base = get_marneo_dir() / "employees" / employee_name / "memory" / "episodes"
        store = EpisodeStore(base / "index.db")
        return cls(store, base / "vectors.npy")
