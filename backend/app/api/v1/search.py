"""Search endpoint — full pipeline implementation.

Pipeline (no LLM anywhere in the serving path):
  query_processing.process_query →
  search.hybrid_orchestrator.search_knowledge_base →
  ranking.rrf.rank_fusion →
  ranking.reranker.rerank (optional, cross-encoder) →
  response.package_builder.build_response_package →
  response.validation.validate_package →
  audit.audit_logger.log_query

Every response field traces back verbatim to a source chunk.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.audit.audit_logger import AuditLogEntry, log_query
from app.auth.rbac import resolve_user_departments
from app.config import settings
from app.db.postgres.session import acquire
from app.dependencies import require_auth
from app.knowledge_gap.gap_detector import detect_and_log
from app.query_processing.pipeline import process_query
from app.ranking.reranker import rerank
from app.ranking.rrf import rank_fusion
from app.response.confidence_thresholds import route_by_confidence
from app.response.package_builder import build_response_package
from app.response.validation import validate_package
from app.search.hybrid_orchestrator import search_knowledge_base

router = APIRouter()


class SearchRequest(BaseModel):
    query: str


class SearchResponse(BaseModel):
    response_id: str
    title: str
    excerpts: list[dict]
    confidence: float
    routing: str
    related_questions: list[str]


@router.post("/", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    user: Annotated[dict, Depends(require_auth)],
) -> SearchResponse:
    """Search the knowledge base for the user's query.

    Returns a ResponsePackage with retrieved excerpts — never synthesized
    text. Full pipeline: process_query → hybrid_search → rrf_rank →
    package_builder → validate → audit_log.
    """
    start_ms = time.time() * 1000

    # Phase 3: Query processing (pure function, no I/O)
    plan = process_query(request.query)

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
            title="No Results",
            excerpts=[],
            confidence=0.0,
            routing="no_answer",
            related_questions=[],
        )

    sub_query_texts = [sq.expanded for sq in plan.sub_queries]

    # Phase 4: Hybrid search (BM25 + pgvector, single SQL query)
    with acquire() as conn:
        result = search_knowledge_base(
            conn=conn,
            sub_queries=sub_query_texts,
            user=user,
        )

    # Build lookup for ranking
    chunk_lookup = {c.chunk_id: c.__dict__ for c in result.candidates}

    # Phase 4: RRF rank fusion
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

    ranked = rank_fusion(
        bm25_ranked=bm25_ranked,
        vector_ranked=vector_ranked,
        chunk_lookup=chunk_lookup,
    )

    # Optional cross-encoder reranking (Phase 4b)
    if settings.rerank_enabled and ranked:
        rerank_candidates = [
            {"chunk_id": c.chunk_id, "content": c.content}
            for c in ranked[: settings.bm25_limit]
        ]
        rerank_result = rerank(
            query=request.query,
            candidates=rerank_candidates,
            top_k=min(10, len(rerank_candidates)),
        )
        rerank_order = {c["chunk_id"]: i for i, c in enumerate(rerank_result)}
        ranked.sort(
            key=lambda c: rerank_order.get(c.chunk_id, len(rerank_order)),
        )

    # Phase 5: Package + validate

    user_depts = resolve_user_departments(user)
    package = build_response_package(
        candidates=ranked,
        query_text=request.query,
        user_departments=user_depts,
    )

    package.routing = route_by_confidence(package.confidence)

    # Knowledge gap detection (best-effort — never raises)
    intent = plan.sub_queries[0].intent if plan.sub_queries else "general"
    if package.routing in ("no_answer", "partial"):
        detect_and_log(
            query=request.query,
            intent=intent,
            confidence=package.confidence,
        )

    # Safety-net validation
    valid, reason = validate_package(package, user)
    if not valid:
        log_query(AuditLogEntry(
            user_id=user["id"],
            query=request.query,
            sub_queries=[sq.display for sq in plan.sub_queries],
            retrieved_ids=[],
            confidence=0.0,
            response_id=package.response_id,
            outcome=f"validation_failed:{reason}",
            latency_ms=time.time() * 1000 - start_ms,
        ))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Response validation failed: {reason}",
        )

    # Audit log
    latency_ms = time.time() * 1000 - start_ms
    log_query(AuditLogEntry(
        user_id=user["id"],
        query=request.query,
        sub_queries=[sq.display for sq in plan.sub_queries],
        retrieved_ids=[c.chunk_id for c in ranked[:25]],
        confidence=round(package.confidence, 1),
        response_id=package.response_id,
        outcome=package.routing,
        latency_ms=round(latency_ms, 1),
    ))

    return SearchResponse(
        response_id=package.response_id,
        title=package.title,
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
        related_questions=[sq.display for sq in plan.sub_queries[:3]] if plan.sub_queries else [],
    )
