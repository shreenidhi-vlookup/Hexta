"""Scoring: apply configurable weights to combine BM25 + vector scores.

Reads weights from ranking/weights_config.py (config, not constants).
This is a simpler linear combination that can be used as an alternative
to RRF or as a secondary signal.
"""

from __future__ import annotations

from typing import Sequence

from app.ranking.weights_config import DEFAULT_WEIGHTS, RankingWeights


def compute_scores(
    candidates: Sequence[dict],
    weights: RankingWeights = DEFAULT_WEIGHTS,
) -> list[tuple[int, float]]:
    """Apply weighted linear combination to candidate scores.

    Each candidate dict must have 'chunk_id', 'bm25_score', and 'vec_score'.
    Returns list of (chunk_id, combined_score) sorted descending.
    """
    scored: list[tuple[int, float]] = []

    for c in candidates:
        score = (
            weights.bm25_weight * float(c.get("bm25_score", 0.0))
            + weights.vector_weight * float(c.get("vec_score", 0.0))
        )
        scored.append((c["chunk_id"], score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
