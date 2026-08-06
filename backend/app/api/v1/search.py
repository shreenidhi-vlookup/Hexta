"""Search endpoint — full pipeline implementation.

Pipeline (no LLM anywhere in the serving path):
  coreference resolution (conversation context) →
  query_processing.process_query (normalize → split → per sub-query:
    spell-correct → entities → intent → expansion + scenario concepts) →
  per sub-query: search.hybrid_orchestrator.search_knowledge_base →
    ranking.rrf.rank_fusion → ranking.reranker.rerank (optional) →
    response.package_builder.build_response_package →
    response.validation.validate_package →
  response assembly (per-question answer blocks, completeness check) →
  audit.audit_logger.log_query

Every response field traces back verbatim to a source chunk.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.audit.audit_logger import AuditLogEntry, log_query
from app.auth.rbac import resolve_user_departments
from app.config import settings
from app.db.postgres.session import acquire
from app.dependencies import require_auth
from app.knowledge_gap.gap_detector import detect_and_log
from app.query_processing import alias_resolver
from app.query_processing import comparison, coreference
from app.query_processing.pipeline import process_query
from app.ranking.reranker import rerank
from app.ranking.rrf import rank_fusion
from app.response.confidence_thresholds import route_by_confidence
from app.response.package_builder import build_response_package
from app.response.validation import validate_package
from app.search.hybrid_orchestrator import search_knowledge_base

router = APIRouter()


class HistoryTurn(BaseModel):
    """One prior (user question, assistant answer) turn."""

    question: str
    answer: str | None = None


class SearchRequest(BaseModel):
    query: str
    history: list[HistoryTurn] = []


class AnswerBlock(BaseModel):
    """A single answer for a single sub-question."""

    question: str
    title: str
    answer_phrase: str
    excerpts: list[dict]
    confidence: float
    routing: str


class SearchResponse(BaseModel):
    response_id: str
    answers: list[AnswerBlock]
    title: str
    answer_phrase: str
    excerpts: list[dict]
    confidence: float
    routing: str
    related_questions: list[str]
    answered: int
    total: int
    comparison: bool = False


def _rank_sub_query(conn, text: str, user: dict):
    """Run hybrid search + RRF for a single sub-query text."""
    result = search_knowledge_base(conn=conn, sub_queries=[text], user=user)
    chunk_lookup = {c.chunk_id: c.__dict__ for c in result.candidates}

    bm25_ranked = sorted(
        [(c.chunk_id, c.bm25_score) for c in result.candidates],
        key=lambda x: x[1],
        reverse=True,
    )
    vector_ranked = sorted(
        [(c.chunk_id, c.vec_score) for c in result.candidates],
        key=lambda x: x[1],
        reverse=True,
    )
    return rank_fusion(
        bm25_ranked=bm25_ranked,
        vector_ranked=vector_ranked,
        chunk_lookup=chunk_lookup,
    )


def _build_block(conn, question: str, search_text: str, user: dict) -> tuple[AnswerBlock, list[int]]:
    """Build one AnswerBlock for a sub-question (search + rank + validate).

    Returns ``(block, retrieved_chunk_ids)``.
    """
    ranked = _rank_sub_query(conn, search_text, user)

    if settings.rerank_enabled and ranked:
        rerank_candidates = [
            {"chunk_id": c.chunk_id, "content": c.content}
            for c in ranked[: settings.bm25_limit]
        ]
        rerank_result = rerank(
            query=question,
            candidates=rerank_candidates,
            top_k=min(10, len(rerank_candidates)),
        )
        rerank_order = {c["chunk_id"]: i for i, c in enumerate(rerank_result)}
        ranked.sort(key=lambda c: rerank_order.get(c.chunk_id, len(rerank_order)))

    user_depts = resolve_user_departments(user)
    package = build_response_package(
        candidates=ranked,
        query_text=question,
        user_departments=user_depts,
    )
    package.routing = route_by_confidence(package.confidence)

    valid, reason = validate_package(package, user)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Response validation failed: {reason}",
        )

    block = AnswerBlock(
        question=question,
        title=package.title,
        answer_phrase=package.answer_phrase,
        excerpts=[
            {
                "text": e.text,
                "source": {
                    "title": e.source.title,
                    "section": e.source.section,
                    "chunk_type": e.source.chunk_type,
                },
                "confidence": e.confidence,
            }
            for e in package.excerpts
        ],
        confidence=package.confidence,
        routing=package.routing,
    )
    return block, [c.chunk_id for c in ranked[:25]]


def _pick_primary(blocks: list[AnswerBlock]) -> AnswerBlock | None:
    """Best block: highest-confidence answered block, else highest-confidence."""
    if not blocks:
        return None
    answered = [b for b in blocks if b.routing in ("answer", "partial")]
    pool = answered or blocks
    return max(pool, key=lambda b: b.confidence)


@router.post("/", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    user: Annotated[dict, Depends(require_auth)],
) -> SearchResponse:
    """Search the knowledge base for the user's query.

    Returns one AnswerBlock per identified sub-question. Every answer is
    extracted verbatim from a source chunk — never synthesized. The
    top-level fields mirror the primary (best) block for compatibility
    with single-question clients.
    """
    start_ms = time.time() * 1000

    history = [h.model_dump() for h in request.history] if request.history else []
    raw = coreference.resolve_references(request.query, history)
    plan = process_query(raw)

    if not plan.sub_queries:
        log_query(AuditLogEntry(
            user_id=user["id"],
            query=request.query,
            sub_queries=[],
            retrieved_ids=[],
            confidence=0.0,
            response_id="",
            outcome="no_sub_queries",
            latency_ms=time.time() * 1000 - start_ms,
        ))
        return SearchResponse(
            response_id="",
            answers=[],
            title="No Results",
            answer_phrase="",
            excerpts=[],
            confidence=0.0,
            routing="no_answer",
            related_questions=[],
            answered=0,
            total=0,
            comparison=False,
        )

    # Build the list of (question_label, search_text) units.
    # A comparison sub-question expands into two operand units.
    work: list[tuple[str, str]] = []
    is_comparison = (
        len(plan.sub_queries) == 1
        and comparison.is_comparison(plan.sub_queries[0].text)
    )
    for sq in plan.sub_queries:
        operands = comparison.extract_comparison_operands(sq.text)
        if operands:
            left, right = operands
            work.append((left, left))
            work.append((right, right))
        else:
            work.append((sq.display, sq.expanded))

    blocks: list[AnswerBlock] = []
    retrieved_ids: list[int] = []

    with acquire() as conn:
        for question, search_text in work:
            # Enrich with doc-derived aliases (e.g. acronyms like SAR).
            extra = alias_resolver.resolve_doc_aliases(conn, search_text)
            enriched = " ".join(
                [search_text] + [e for e in extra if e not in search_text]
            ).strip()
            block, block_ids = _build_block(conn, question, enriched or search_text, user)
            blocks.append(block)
            retrieved_ids.extend(block_ids)

    primary = _pick_primary(blocks)
    primary = primary or AnswerBlock(
        question="", title="No Results Found", answer_phrase="",
        excerpts=[], confidence=0.0, routing="no_answer",
    )

    answered = sum(1 for b in blocks if b.routing in ("answer", "partial"))
    total = len(blocks)
    response_id = hashlib.sha256(
        f"{raw}:{primary.confidence}:{uuid.uuid4()}".encode()
    ).hexdigest()[:16]

    # Knowledge gap detection (best-effort — never raises).
    for block in blocks:
        if block.routing in ("no_answer", "partial"):
            detect_and_log(
                query=block.question or raw,
                intent="general",
                confidence=block.confidence,
            )

    # Audit log (single entry per request, aggregated).
    latency_ms = time.time() * 1000 - start_ms
    log_query(AuditLogEntry(
        user_id=user["id"],
        query=request.query,
        sub_queries=[sq.display for sq in plan.sub_queries],
        retrieved_ids=retrieved_ids[:25],
        confidence=round(primary.confidence, 1),
        response_id=response_id,
        outcome=primary.routing,
        latency_ms=round(latency_ms, 1),
    ))

    return SearchResponse(
        response_id=response_id,
        answers=blocks,
        title=primary.title,
        answer_phrase=primary.answer_phrase,
        excerpts=primary.excerpts,
        confidence=primary.confidence,
        routing=primary.routing,
        related_questions=[sq.display for sq in plan.sub_queries[:3]],
        answered=answered,
        total=total,
        comparison=is_comparison,
    )
