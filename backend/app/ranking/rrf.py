"""Reciprocal Rank Fusion (RRF) — combines BM25 and vector rankings.

RRF is chosen for its simplicity and parameter-free nature on micro-tier
hardware. Each candidate's final score is:

    score = sum(weight_i / (k + rank_i))  for each result list i

where k is the RRF constant (default 60), rank_i is the position
(1-indexed) of the candidate in list i, and weight_i is that list's
configured weight (ranking/weights_config.py: 0.3 BM25 / 0.7 vector by
default). The weights exist specifically so vector similarity -- the
more reliable signal per that config's calibration notes -- gets more
say than keyword overlap; an earlier version of this function summed
the two reciprocal ranks unweighted (1:1), silently discarding
DEFAULT_WEIGHTS and letting a chunk with strong keyword overlap on
generic recurring words (e.g. "loan" appearing five times) outrank a
chunk with much better semantic relevance, verified live for "What is
the minimum down payment for a VA loan?": the one chunk that actually
answers it ranked #2 on vector similarity but lost to an unrelated
chunk that merely had more incidental keyword overlap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.ranking.weights_config import DEFAULT_WEIGHTS, RankingWeights


@dataclass
class RankedCandidate:
    chunk_id: int
    document_id: int
    content: str
    title: str
    section: str | None
    chunk_type: str
    department: str
    bm25_score: float
    vec_score: float
    rrf_score: float
    combined_rank: int
    is_approved: bool
    document_version: int
    client_id: str | None = None


RRF_K: int = 60  # standard RRF constant


def rank_fusion(
    bm25_ranked: Sequence[tuple[int, float]],
    vector_ranked: Sequence[tuple[int, float]],
    chunk_lookup: dict[int, dict],
    k: int = RRF_K,
    weights: RankingWeights = DEFAULT_WEIGHTS,
) -> list[RankedCandidate]:
    """Fuse two ranked lists using weighted RRF.

    Args:
        bm25_ranked: list of (chunk_id, bm25_score) in descending score order
        vector_ranked: list of (chunk_id, vec_score) in descending score order
        chunk_lookup: dict mapping chunk_id -> chunk metadata dict
        k: RRF constant (higher = flatter curve)
        weights: per-list weights (ranking/weights_config.py) applied to
            each list's reciprocal rank before summing -- see module
            docstring for why this must not default to an unweighted 1:1
            sum.

    Returns:
        List of RankedCandidate sorted by RRF score descending.
    """
    ranks: dict[int, dict] = {}

    for rank, (cid, score) in enumerate(bm25_ranked, start=1):
        if cid not in ranks:
            ranks[cid] = {"bm25_score": score, "vec_score": 0.0, "bm25_rank": rank, "vec_rank": 9999}
        else:
            ranks[cid]["bm25_score"] = score
            ranks[cid]["bm25_rank"] = rank

    for rank, (cid, score) in enumerate(vector_ranked, start=1):
        if cid not in ranks:
            ranks[cid] = {"bm25_score": 0.0, "vec_score": score, "bm25_rank": 9999, "vec_rank": rank}
        else:
            ranks[cid]["vec_score"] = score
            ranks[cid]["vec_rank"] = rank

    results: list[RankedCandidate] = []
    for cid, r in ranks.items():
        rrf_score = (
            weights.bm25_weight * (1.0 / (k + r["bm25_rank"]))
            + weights.vector_weight * (1.0 / (k + r["vec_rank"]))
        )
        meta = chunk_lookup.get(cid, {})
        results.append(RankedCandidate(
            chunk_id=cid,
            content=meta.get("content", ""),
            document_id=meta.get("document_id", 0),
            title=meta.get("title", ""),
            section=meta.get("section"),
            chunk_type=meta.get("chunk_type", "paragraph"),
            department=meta.get("department", ""),
            bm25_score=r["bm25_score"],
            vec_score=r["vec_score"],
            rrf_score=rrf_score,
            combined_rank=0,
            is_approved=meta.get("is_approved", True),
            document_version=meta.get("document_version", 1),
            client_id=meta.get("client_id"),
        ))

    results.sort(key=lambda c: c.rrf_score, reverse=True)
    for i, c in enumerate(results):
        c.combined_rank = i + 1

    return results
