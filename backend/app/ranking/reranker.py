"""Cross-encoder reranker using an ONNX quantized model.

Scores only the top-N RRF candidates to stay within the <200ms p95
latency budget (CLAUDE.md rule #6).

Runs on FastEmbed + onnxruntime -- the same two dependencies the query
embedder already uses -- rather than transformers/torch, which the
previous implementation imported. That import could never succeed here:
torch alone is an order of magnitude larger than the backend's whole
memory cap (CLAUDE.md rule #10), so the reranker silently fell back to
RRF order on every call. ms-marco-MiniLM-L-6-v2 is ~80MB quantized and
loads through the onnxruntime already in the image.

Why a cross-encoder at all: RRF fuses two rankings that each score the
query and the chunk *separately*, so neither ever sees the pair
together. Measured on the eval set, the correct chunk was inside the
top 5 for 92.3% of queries but ranked first for only 69.2% -- the gap
is precisely what a pairwise scorer is for.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Sequence

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_reranker():
    """Lazily load and cache the cross-encoder.

    Cached for the process lifetime: the previous implementation built
    its scorer inside rerank(), reloading the model on every request,
    which cannot fit any per-query latency budget.
    """
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    logger.info("Loading reranker model: %s", settings.rerank_model)
    return TextCrossEncoder(
        model_name=settings.rerank_model,
        cache_dir=settings.rerank_cache_dir,
    )


def rerank(
    query: str,
    candidates: Sequence[dict],
    top_k: int = 10,
) -> list[dict]:
    """Re-rank the top-k candidates using a cross-encoder model.

    Args:
        query: The original user query string.
        candidates: List of candidate dicts with 'chunk_id' and 'content'.
        top_k: Number of candidates to re-rank (default 10).

    Returns:
        List of candidates sorted by cross-encoder score descending.
        Never raises: any failure falls back to the incoming RRF order,
        so a reranker problem degrades ranking quality rather than
        taking the search endpoint down.
    """
    if not settings.rerank_enabled or not candidates:
        return list(candidates)[:top_k]

    top_candidates = list(candidates)[:top_k]

    try:
        model = _get_reranker()
        documents = [c.get("content", "") for c in top_candidates]
        scores = list(model.rerank(query, documents))
    except Exception as exc:
        logger.warning("Reranking failed, falling back to RRF order: %s", exc)
        return top_candidates

    if len(scores) != len(top_candidates):
        # Defensive: pair scores back onto candidates strictly by
        # position, so a length mismatch can never silently attach one
        # document's score to another's chunk.
        logger.warning(
            "Reranker returned %d scores for %d candidates; keeping RRF order",
            len(scores), len(top_candidates),
        )
        return top_candidates

    for candidate, score in zip(top_candidates, scores):
        candidate["rerank_score"] = float(score)

    top_candidates.sort(key=lambda c: c.get("rerank_score", 0.0), reverse=True)
    return top_candidates
