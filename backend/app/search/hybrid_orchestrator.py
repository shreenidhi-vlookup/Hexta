"""Hybrid search orchestrator.

Combines BM25 (full-text) and pgvector (semantic) search into a single
PostgreSQL query. RBAC and active-version filtering are in the WHERE
clause (CLAUDE.md rule #1).

This uses the single-query pattern — vector and BM25 in the same SQL
statement, not separate round-trips to separate services.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from psycopg import Connection

from app.ranking.rrf import RRF_K
from app.ranking.weights_config import DEFAULT_WEIGHTS
from app.search.bm25_search import build_tsquery
from app.search.metadata_filters import get_search_filter
from app.search.pgvector_search import embed_query

logger = logging.getLogger(__name__)


@dataclass
class SearchCandidate:
    chunk_id: int
    document_id: int
    title: str
    doc_type: str
    department: str
    section: str | None
    chunk_type: str
    content: str
    is_approved: bool
    document_version: int
    bm25_score: float
    vec_score: float
    client_id: str | None = None


@dataclass
class SearchResult:
    candidates: list[SearchCandidate] = field(default_factory=list)
    query_embedding: list[float] = field(default_factory=list)
    sub_query: str = ""


def search_knowledge_base(
    conn: Connection,
    sub_queries: Sequence[str],
    user: dict | None,
    bm25_limit: int = 25,
    vector_limit: int = 25,
    max_results: int = 100,
) -> SearchResult:
    """Run hybrid search for a set of sub-queries.

    Returns ranked candidates with both BM25 and vector scores.
    RBAC is applied in the WHERE clause per CLAUDE.md rule #1.
    """
    if not sub_queries:
        return SearchResult()

    primary_query = sub_queries[0]
    query_vector = embed_query(primary_query)

    combined_text = " ".join(sub_queries)
    tsquery = build_tsquery(combined_text)

    # RBAC filter — applied in WHERE clause
    rbac_clause, rbac_params = get_search_filter(user)

    # A chunk is admitted to the candidate set if EITHER it has some BM25
    # keyword overlap OR its vector similarity clears min_vector_similarity
    # on its own. BM25 match used to be a hard, unconditional WHERE-clause
    # gate: a well-formed, correctly-spelled paraphrase that shares no
    # vocabulary with the relevant chunk ("how do lenders verify I have a
    # job" vs. a chunk about "employment verification") returned zero
    # candidates, because pgvector's semantic match was never even
    # considered once the tsquery filter excluded the row — defeating the
    # point of hybrid search. Dropping the gate entirely isn't safe either:
    # without any floor, truly nonsensical queries also always retrieve
    # *something* (whatever's nearest in embedding space), which downstream
    # RRF/confidence logic can inflate into a false high-confidence answer.
    # The similarity floor is the calibrated middle ground — see
    # ranking/weights_config.py for the calibration data.
    where_parts: list[str] = [
        "c.is_active = true",
        "c.is_approved = true",
        "d.is_active = true",
        "d.is_approved = true",
        "c.embedding IS NOT NULL",
        "(c.fts @@ to_tsquery('english', %s) OR (1 - (c.embedding <=> %s)) >= %s)",
    ]
    where_params: list = [tsquery, query_vector, DEFAULT_WEIGHTS.min_vector_similarity]

    if rbac_clause:
        where_parts.append(rbac_clause)
        where_params.extend(rbac_params)

    where_clause = " AND ".join(where_parts)

    # Combine BM25 and vector scores by RANK (Reciprocal Rank Fusion), not
    # by their raw values. The two scores live on different, incompatible
    # scales: ts_rank_cd is unbounded and commonly lands well above 1.0 for
    # a chunk with several term hits, while cosine similarity is bounded to
    # roughly [0, 1] (see ranking/weights_config.py's calibration notes).
    # The previous ORDER BY combined them directly as
    # `bm25_score * 0.3 + vec_score * 0.7`, so a chunk with a merely
    # decent BM25 score (say 1.3, from several generic recurring words
    # like "loan") could numerically swamp a chunk with a much better,
    # well-calibrated vector match (0.76 vs 0.69) despite BM25 supposedly
    # being the minority signal at 30% weight -- 0.3 of an unbounded
    # number isn't actually 30% of the combined score once the other term
    # is capped near 1. Verified live: for "What is the minimum down
    # payment for a VA loan?", the one chunk that actually answers it
    # (a table row) ranked #2 on vector similarity (0.76) but #9 on raw
    # BM25 score, and lost to an unrelated FHA chunk (BM25 1.3, vector
    # 0.69: 1.3*0.3 + 0.69*0.7 = 0.87 vs the right chunk's
    # 0.4*0.3 + 0.76*0.7 = 0.65). Ranking each list first and fusing by
    # 1/(k+rank) -- the same RRF_K-based formula ranking/rrf.py already
    # implements but was never wired into this query -- makes the two
    # signals commensurable regardless of either score's raw magnitude,
    # so the properly-weighted 70% vector preference actually applies.
    # Still a single SQL statement (CLAUDE.md rule #3): both rankings are
    # computed as window functions over the same filtered candidate set.
    query = f"""
    WITH scored AS (
        SELECT c.id, c.document_id, d.title, d.doc_type, c.section,
               c.chunk_type, c.content, c.department,
               c.is_approved AS chunk_is_approved,
               d.client_id, d.version AS document_version,
               ts_rank_cd(c.fts, to_tsquery('english', %s)) AS bm25_score,
               1 - (c.embedding <=> %s) AS vec_score,
               RANK() OVER (
                   ORDER BY ts_rank_cd(c.fts, to_tsquery('english', %s)) DESC
               ) AS bm25_rank,
               RANK() OVER (
                   ORDER BY (1 - (c.embedding <=> %s)) DESC
               ) AS vec_rank
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE {where_clause}
    )
    SELECT id, document_id, title, doc_type, section, chunk_type, content,
           department, chunk_is_approved, client_id, document_version,
           bm25_score, vec_score,
           (%s / (%s + bm25_rank)::float) + (%s / (%s + vec_rank)::float) AS rrf_score
    FROM scored
    ORDER BY rrf_score DESC
    LIMIT %s
    """

    params: list = [
        tsquery,
        query_vector,
        tsquery,
        query_vector,
    ]
    params.extend(where_params)
    params.extend([
        DEFAULT_WEIGHTS.bm25_weight, RRF_K,
        DEFAULT_WEIGHTS.vector_weight, RRF_K,
        max_results,
    ])

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    candidates = []
    for row in rows:
        candidates.append(SearchCandidate(
            chunk_id=row["id"],
            document_id=row["document_id"],
            title=row["title"],
            doc_type=row["doc_type"],
            department=row["department"],
            section=row["section"],
            chunk_type=row["chunk_type"],
            content=row["content"],
            is_approved=bool(row["chunk_is_approved"]),
            document_version=int(row["document_version"] or 1),
            bm25_score=float(row["bm25_score"] or 0.0),
            vec_score=float(row["vec_score"] or 0.0),
            client_id=row["client_id"],
        ))

    logger.info(
        "Hybrid search: %d sub-queries, %d candidates returned",
        len(sub_queries), len(candidates),
    )

    return SearchResult(
        candidates=candidates,
        query_embedding=query_vector,
        sub_query=combined_text,
    )
