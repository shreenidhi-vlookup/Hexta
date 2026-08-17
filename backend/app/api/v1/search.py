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
import re
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
from app.query_processing import alias_resolver, corpus_vocab, domain_terms
from app.query_processing import comparison, coreference, scope_guard
from app.query_processing.pipeline import process_query
from app.ranking.reranker import rerank
from app.ranking.rrf import rank_fusion
from app.response import answerability
from app.response.confidence_thresholds import route_by_confidence
from app.response.followup_questions import has_domain_topic, suggest_followups
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
    ranked = rank_fusion(
        bm25_ranked=bm25_ranked,
        vector_ranked=vector_ranked,
        chunk_lookup=chunk_lookup,
    )
    return _apply_fragment_penalty(ranked)


# The cross-encoder reranker can only afford to score `rerank_top_k`
# candidates (CLAUDE.md rule 6's <200ms budget -- measured live, scoring
# all `bm25_limit` candidates costs 1154ms p95 at n=25 vs 191ms at n=5),
# so it never sees anything RRF placed below that cutoff. RRF's rank-based
# fusion means a chunk that's a near-tie with the window's weakest member
# can still land one rank outside it and be permanently invisible to the
# reranker, even when it would score far better once actually evaluated.
#
# Measured live: for "What does a lender check before approving a
# mortgage?", the correct glossary definition (Underwriting) sat at RRF
# rank 6 against a window of 5 -- effectively tied with rank 5
# (rrf_score 0.01484 vs 0.01486) -- while the window's rank-1 slot held a
# different, wrong glossary chunk (Prepayment Penalty) from the very same
# document. That ruled out a document-diversity framing: both the right
# and wrong chunks came from the same source, so "make sure more than one
# document is represented" does nothing here -- the document was already
# represented, just by the wrong chunk. What actually pushed the right
# one out was four SOP chunks occupying ranks 2-5 on partial lexical
# overlap. The fix that matches the evidence is score proximity, not
# document identity: rescue a near-miss candidate regardless of which
# document it's from, and only when its RRF score is close enough to the
# window's weakest member that rank alone -- not relevance -- explains why
# it's outside. At zero extra cross-encoder cost, since the number of
# candidates scored is unchanged.
#
# _MIN_RESCUE_SCORE_RATIO stays deliberately strict (0.9, i.e. within 10%
# of the weakest window score) precisely because it ignores document
# identity: with nothing else gating it, a loose ratio would pull in any
# plausible-looking chunk from anywhere in the lookahead purely because a
# large document floods the corpus with partial matches. A tight ratio
# means only genuine near-ties get rescued.
#
# _MAX_RESCUE_SWAPS is 1, not 2: an earlier version allowed 2 and had a
# real bug -- after the first swap replaces window[-1], the window is
# re-sorted and the just-rescued candidate becomes the new window[-1]
# (it's always the smallest of the bunch, since candidates only get
# picked from ranks below the original window). A second swap then
# targets window[-1] again and evicts the very candidate the first swap
# just rescued, for something worse. The measured finding only ever
# needed one rescue; capping at 1 sidesteps the eviction bug entirely
# rather than adding bookkeeping to track which original slot each swap
# should target.
_MAX_RESCUE_SWAPS = 1
# The lookahead depth costs nothing -- it's a Python list scan, not
# cross-encoder scoring, which only ever runs on `top_k` candidates
# regardless of how far the lookahead searches. The relevance guard is
# entirely `_MIN_RESCUE_SCORE_RATIO`; there's no latency reason to keep
# the lookahead shallow. Searching the full bm25_limit candidate pool
# matches two further live findings (2026-08-17) where the correct
# glossary chunk was diluted past rank 15, not just one rank outside
# the window: "How can I calculate the value I have in my property?"
# and "Who collects my monthly mortgage payment after closing?".
_RESCUE_LOOKAHEAD = None  # None => search the full candidate list passed in
_MIN_RESCUE_SCORE_RATIO = 0.9


def _diversify_rerank_window(ranked: list, top_k: int) -> list:
    """Rescue near-miss candidates RRF placed just outside the window.

    Walks the RRF order just past the naive top_k window (see
    `_RESCUE_LOOKAHEAD`) for candidates whose RRF score is within
    `_MIN_RESCUE_SCORE_RATIO` of the window's weakest member -- a sign
    the cutoff, not relevance, is why they're outside it -- and swaps up
    to `_MAX_RESCUE_SWAPS` of them in for the weakest window slots.
    Deliberately ignores document identity (see module comment above):
    the two chunks that motivated this can come from the same document.

    Only reorders which candidates are in the window; the reranker's own
    cross-encoder sort decides the final order of whatever it receives.
    """
    if top_k >= len(ranked) or top_k == 0:
        return ranked

    window = list(ranked[:top_k])
    lookahead = (
        ranked[top_k:]
        if _RESCUE_LOOKAHEAD is None
        else ranked[top_k : top_k + _RESCUE_LOOKAHEAD]
    )
    swaps = 0

    for candidate in lookahead:
        if swaps >= _MAX_RESCUE_SWAPS:
            break
        weakest = window[-1]
        if weakest.rrf_score <= 0:
            break
        if candidate.rrf_score < weakest.rrf_score * _MIN_RESCUE_SCORE_RATIO:
            # Candidates only get further from the window's score as we
            # walk deeper into the lookahead, so nothing later qualifies.
            break
        window[-1] = candidate
        window.sort(key=lambda c: c.rrf_score, reverse=True)
        swaps += 1

    return window + list(ranked[top_k:])


# Words that make a question a "bare follow-up": it carries no topic of
# its own after question-starters and common words are removed. Such a
# question is unanswerable in isolation ("what happens next?"), so its
# RRF score (which is inflated for short generic queries) must not be
# presented as a high-confidence answer.
_BARE_FOLLOWUP_WORDS = frozenset((
    "this", "that", "it", "its", "these", "those", "them", "they",
    "you", "your", "me", "my", "we", "us", "ours",
    "work", "works", "working", "workings",
    "happen", "happens", "happened", "next", "then", "afterwards",
    "mean", "means", "meant", "meaning", "explain", "explained",
    "explanation", "actually", "exactly", "simply", "basically",
    "more", "further", "else", "anything", "something", "thing", "things",
    "about", "info", "information", "details", "detail", "relevant",
    "rules", "rule", "go", "goes", "going", "fine", "okay", "ok",
))

# Cap confidence for bare follow-ups so they never route as a full answer.
_BARE_FOLLOWUP_CONFIDENCE_CAP = 74.0

# Chunks whose content begins with a lowercase letter start mid-word —
# the generated QA source documents were hard-cut at ~500 chars, so a
# chunk often opens with a word fragment ("l mortgages", "ents.",
# "ransfer"). Such chunks over-match keyword queries but make poor answer
# sources; their RRF score is dampened so cleanly-starting chunks surface.
_FRAGMENT_START_RE = re.compile(r"^[a-z]")
_FRAGMENT_FOOTER_START_RE = re.compile(r"^\(\s*generated")
# How much of the RRF score a fragment-starting chunk retains.
_FRAGMENT_PENALTY = 0.35


def _apply_fragment_penalty(ranked: list) -> list:
    """Dampen RRF scores of chunks that start mid-word, then re-rank."""
    for c in ranked:
        content = (c.content or "").lstrip()
        if content and (
            _FRAGMENT_START_RE.match(content)
            or _FRAGMENT_FOOTER_START_RE.match(content)
        ):
            c.rrf_score = c.rrf_score * _FRAGMENT_PENALTY
    ranked.sort(key=lambda c: c.rrf_score, reverse=True)
    return ranked


def _content_words(question: str) -> list[str]:
    """Non-question-starter, non-common words in a question (its 'content')."""
    words = [w for w in re.split(r"[^a-z']+", question.lower()) if w]
    return [
        w for w in words
        if w not in domain_terms.QUESTION_STARTERS
        and w not in domain_terms.COMMON_WORDS
    ]


def _is_bare_followup(question: str) -> bool:
    """True when the question reduces to ≤2 generic words after removing
    question starters and common words (i.e. it names no real subject)."""
    content = _content_words(question)
    return 1 <= len(content) <= 2 and all(w in _BARE_FOLLOWUP_WORDS for w in content)


def _dampen_generic_confidence(
    question: str,
    answer_text: str,
    confidence: float,
) -> float:
    """Cap the confidence of a question that has no real subject.

    Two cases are caught:
    1. A bare follow-up ("what happens next?") — no content at all.
    2. An off-topic question with no domain topic whose top excerpt
       shares none of the question's content words ("what is the
       weather like?"). Its RRF score is inflated by common words, so
       presenting it as a high-confidence answer would be misleading.
    """
    if _is_bare_followup(question):
        return min(confidence, _BARE_FOLLOWUP_CONFIDENCE_CAP)
    if has_domain_topic(question):
        return confidence
    content = _content_words(question)
    if not content:
        return confidence
    haystack = (answer_text or "").lower()
    if any(w in haystack for w in content):
        return confidence
    return min(confidence, _BARE_FOLLOWUP_CONFIDENCE_CAP)


# --- Phase B: query↔answer relevance gate -------------------------------

# Moved to query_processing/relevance.py so response/package_builder.py can
# use the same scoring for answer-phrase selection without a circular
# import (search.py already imports build_response_package from
# package_builder.py). Re-exported here under the original underscore
# names so existing callers/tests (test_search_dampening.py) are unaffected.
from app.query_processing.relevance import (  # noqa: E402
    _RELEVANCE_STOP,
    query_content_terms as _query_content_terms,
    relevance_factor as _relevance_factor,
    term_present as _term_present,
    term_stem_candidates as _term_stem_candidates,
)


def _recalibrate_confidence(confidence: float, relevance: float) -> float:
    """Scale confidence down for weak query↔answer relevance (never up).

    Piecewise so on-topic answers are preserved while off-topic chunks are
    punished hard:
      * relevance ≥ 0.70  → unchanged.  (On-topic answers with a few
        morphological misses stay above the 'answer' threshold.)
      * 0.35 ≤ rel < 0.70 → mild linear drop  (→ ~55% at 0.35, → 100% at 0.70).
      * rel < 0.35        → aggressive drop   (→ 35% at 0.0).  A wrong-topic
        but top-ranked chunk can no longer keep a ~100 score.
    """
    if relevance >= 0.70:
        return confidence
    if relevance >= 0.35:
        factor = 0.55 + (relevance - 0.35) / 0.35 * 0.45
        return confidence * factor
    factor = 0.35 + relevance / 0.35 * 0.20
    return confidence * factor


def _evidence_relevance(question: str, answer_phrase: str, top_excerpt: str) -> float:
    """Best query↔evidence relevance across the phrase and its excerpt.

    The question this gate is really asking is "is the retrieved evidence
    on-topic?", and the answer phrase is only the highlighted fragment of
    that evidence -- so the excerpt as a whole gets a say too, and the
    stronger signal wins.

    Scoring the phrase alone punishes correct but terse answers: the row
    "| VA | 0% for eligible borrowers | 100% |" is exactly the answer to
    "What is the minimum down payment for a VA loan?", yet it repeats only
    one of the question's content terms, scoring 0.25 -- under the 0.35
    floor -- and was forced to no_answer despite the surrounding table
    excerpt (with its "Minimum Down Payment" header and "Loan Type"
    column) being unambiguously on-topic. Scoring the excerpt alone has
    the opposite failure: a long chunk can cover the question's words
    incidentally while the phrase drawn from it is off-topic. Taking the
    max keeps the gate's real job -- catching retrieval that missed the
    topic entirely, where neither the phrase nor its excerpt matches.
    """
    phrase_rel = _relevance_factor(question, answer_phrase) if answer_phrase else 0.0
    excerpt_rel = _relevance_factor(question, top_excerpt) if top_excerpt else 0.0
    return max(phrase_rel, excerpt_rel)


def _apply_relevance_gate(
    question: str,
    answer_phrase: str,
    top_excerpt: str,
    confidence: float,
) -> float:
    """Recalibrate confidence by how well the answer covers the question.

    Falls back to the top excerpt text when no answer phrase was extracted.
    """
    relevance = _evidence_relevance(question, answer_phrase, top_excerpt)
    return _recalibrate_confidence(confidence, relevance)


# --- Phase C: routing safety ---------------------------------------------

# Below this query↔answer relevance the retrieved content is considered
# off-topic and must not be presented as an answer (no-fabrication rule).
_NO_ANSWER_RELEVANCE = 0.35

# Ceiling applied when scope_guard flags a question -- comfortably under
# confidence_thresholds.DEFAULT_THRESHOLDS.low (50), so route_by_confidence
# always lands on no_answer for these regardless of how well retrieval
# happened to score. Not 0: a non-zero, non-trivial number still shows up
# distinctly in the audit log and knowledge_gaps table (gap_detector logs
# a gap for any confidence under that same 50 floor) rather than reading
# identically to a total retrieval miss.
_OUT_OF_SCOPE_CONFIDENCE_CAP = 15.0


def _apply_scope_guard(question: str, confidence: float) -> float:
    """Cap confidence for questions no document lookup could ever answer.

    Relevance-based gating cannot catch these (see scope_guard.py's module
    docstring for why): the retrieved text is genuinely on-topic, so
    relevance scores fine and confidence stays high. This check looks at
    the question itself, independent of what was retrieved or how well it
    scored, and is applied before the relevance gate so a personal-data or
    fraud-intent question is capped even when retrieval happened to find
    unusually on-topic text.
    """
    if scope_guard.out_of_scope_reason(question):
        return min(confidence, _OUT_OF_SCOPE_CONFIDENCE_CAP)
    return confidence


def _decide_routing(
    question: str,
    answer_phrase: str,
    top_excerpt: str,
    confidence: float,
    rerank_score: float | None = None,
) -> str:
    """Decide routing with safety overrides, never fabricating an answer.

    Forces ``no_answer`` when:
      * there is no usable answer phrase (Phase A extracted only
        questions/headings → empty), or
      * the retrieved content shares almost no content terms with the
        question (off-topic retrieval that slipped through ranking), or
      * the cross-encoder affirmatively judges that the evidence does not
        answer the question (see response/answerability.py). This catches
        the complementary failure: a chunk that shares the question's
        vocabulary — so it clears the lexical gate above — while
        answering a different question entirely.
    Otherwise confidence routing (``answer`` | ``partial``) applies.
    """
    if not (answer_phrase or "").strip():
        return "no_answer"
    relevance = _evidence_relevance(question, answer_phrase, top_excerpt)
    if relevance < _NO_ANSWER_RELEVANCE:
        return "no_answer"
    if not answerability.is_answerable(rerank_score):
        return "no_answer"
    return route_by_confidence(confidence)


def _build_block(conn, question: str, search_text: str, user: dict) -> tuple[AnswerBlock, list[int]]:
    """Build one AnswerBlock for a sub-question (search + rank + validate).

    Returns ``(block, retrieved_chunk_ids)``.
    """
    ranked = _rank_sub_query(conn, search_text, user)
    rerank_scores: dict[int, float] = {}

    if settings.rerank_enabled and ranked:
        rerank_top_k = min(settings.rerank_top_k, len(ranked))
        # Only the head of the candidate list is rescored -- cross-encoder
        # cost is linear in candidates and the whole point is to fit the
        # <200ms p95 budget (CLAUDE.md rule 6). Candidates past
        # rerank_top_k keep their RRF order: they all map to the same
        # sort key below, and Python's stable sort preserves it.
        #
        # Before slicing, make sure that head isn't monopolized by one
        # document -- see _diversify_rerank_window's docstring for the
        # measured cross-document interference this guards against.
        # The rescue must see the whole RRF-fused pool (_rank_sub_query
        # computes RRF over up to 100 candidates), not the bm25_limit=25
        # slice below -- two live queries had their correct chunk diluted
        # past rank 25 by SOP volume, not just past the reranker's top 5.
        # bm25_limit is applied after, to cap how many candidates get
        # turned into rerank_candidates; rescue itself is a free list
        # scan, not cross-encoder work, so searching further costs nothing.
        diversified = _diversify_rerank_window(ranked, rerank_top_k)[
            : settings.bm25_limit
        ]
        rerank_candidates = [
            {"chunk_id": c.chunk_id, "content": c.content}
            for c in diversified
        ]
        rerank_result = rerank(
            query=question,
            candidates=rerank_candidates,
            top_k=rerank_top_k,
        )
        rerank_order = {c["chunk_id"]: i for i, c in enumerate(rerank_result)}
        rerank_scores = {
            c["chunk_id"]: c["rerank_score"]
            for c in rerank_result
            if "rerank_score" in c
        }
        ranked.sort(key=lambda c: rerank_order.get(c.chunk_id, len(rerank_order)))

    user_depts = resolve_user_departments(user)
    package = build_response_package(
        candidates=ranked,
        query_text=question,
        user_departments=user_depts,
    )
    package.confidence = _dampen_generic_confidence(
        question,
        package.excerpts[0].text if package.excerpts else "",
        package.confidence,
    )
    # Phase B: relevance gate — scale confidence by how well the answer
    # covers the question's content terms (never raises it).
    package.confidence = _apply_relevance_gate(
        question,
        package.answer_phrase,
        package.excerpts[0].text if package.excerpts else "",
        package.confidence,
    )
    # Phase B.5: scope guard — cap confidence for questions no document
    # lookup could ever answer, independent of relevance (see
    # _apply_scope_guard). Applied after the relevance gate since it must
    # win regardless of how on-topic retrieval happened to score.
    package.confidence = _apply_scope_guard(question, package.confidence)
    # Phase B.6: answerability — the cross-encoder's judgement of the
    # chunk the answer was actually drawn from (None when reranking is
    # off or that chunk was outside the rescored head, in which case the
    # gate abstains).
    answer_rerank_score = rerank_scores.get(ranked[0].chunk_id) if ranked else None
    package.confidence = answerability.cap_confidence(
        package.confidence, answer_rerank_score
    )
    package.routing = _decide_routing(
        question,
        package.answer_phrase,
        package.excerpts[0].text if package.excerpts else "",
        package.confidence,
        answer_rerank_score,
    )

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

    # Refresh the corpus-derived vocabulary before query processing so
    # spell correction can recognise terms that exist only in the user's
    # own documents (see corpus_vocab). TTL-cached, so this is a no-op on
    # all but the first request in each window; process_query itself stays
    # I/O-free.
    with acquire() as conn:
        corpus_vocab.refresh_if_stale(conn)

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

        # Topic-appropriate follow-up suggestions (verified against the KB).
        related_questions = suggest_followups(conn, [sq.text for sq in plan.sub_queries])

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
        related_questions=related_questions,
        answered=answered,
        total=total,
        comparison=is_comparison,
    )
