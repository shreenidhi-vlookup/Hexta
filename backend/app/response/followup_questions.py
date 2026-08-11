"""Deterministic follow-up question suggestions.

Generates up to ``max_questions`` topic-appropriate, non-repeating
follow-up questions based on the domain terms detected in the user's
sub-queries. The questions are curated per canonical topic and are never
a re-echo of the user's own question text.

Each candidate is verified against the active knowledge base with a cheap
``tsquery`` EXISTS check, so suggestions are answerable in the current
deployment. If verification fails (or the KB is empty), the curated
candidates are returned as-is — the fallback is never empty.

Everything here is deterministic and dependency-free (stdlib + psycopg),
matching the "no LLM in the serving path" doctrine.
"""

from __future__ import annotations

import logging

from psycopg import Connection

from app.query_processing import domain_terms
from app.search.bm25_search import build_tsquery

logger = logging.getLogger(__name__)

# Curated follow-up questions per canonical topic. The first entry is the
# most topical. Questions reference content known to exist in the Hexta KB
# so that the verification pass usually keeps them.
TOPIC_FOLLOWUPS: dict[str, list[str]] = {
    "lifetime mortgage": [
        "What happens to a lifetime mortgage when the borrower dies?",
        "Can you move a lifetime mortgage to a new property?",
        "How is a lifetime mortgage repaid?",
        "What are the interest rates on a lifetime mortgage?",
    ],
    "equity release": [
        "What are the risks of equity release?",
        "How does equity release affect inheritance?",
        "What are the costs and fees for equity release?",
        "Can I make early repayment on equity release?",
    ],
    "bridging finance": [
        "What are the costs of bridging finance?",
        "What documents do I need for a bridging loan?",
        "How long does a bridging loan last?",
        "What is the typical term of a bridging loan?",
    ],
    "income protection": [
        "What does income protection insurance cover?",
        "What are the exclusions of income protection insurance?",
        "How long is the deferred period for income protection?",
    ],
    "credit score": [
        "What factors affect my credit score?",
        "How can I improve my credit score?",
        "What is a good credit score for a mortgage?",
    ],
    "interest rate": [
        "What affects the interest rate I am offered?",
        "Can I lock in an interest rate?",
        "What is the difference between fixed and adjustable rates?",
    ],
    "mortgage": [
        "What documents do I need to apply for a mortgage?",
        "What are the eligibility requirements for a mortgage?",
        "How long does a mortgage application take?",
        "What are the interest rates on a mortgage?",
    ],
    "guarantor": [
        "What is a guarantor mortgage?",
        "Can a guarantor be removed from the mortgage later?",
        "What are the risks of being a guarantor?",
    ],
    "remortgage": [
        "What is remortgaging?",
        "What is a product transfer?",
        "What documents do I need to remortgage?",
    ],
    "subject access request": [
        "How long does a subject access request take?",
        "What is included in a subject access request?",
    ],
}

# Canonical topics to scan for, most specific first. Topics not backed by
# a domain term key (guarantor, remortgage) are matched as keywords below.
_TERM_PRIORITY: list[str] = [
    "lifetime mortgage",
    "equity release",
    "bridging finance",
    "income protection",
    "subject access request",
    "credit score",
    "interest rate",
    "remortgage",
    "guarantor",
    "mortgage",
]

# Keyword → topic for topics that are not canonical domain terms.
_KEYWORD_TOPICS: dict[str, str] = {
    "guarantor": "guarantor",
    "remortgage": "remortgage",
    "remortgaging": "remortgage",
    "product transfer": "remortgage",
    "mortgage": "mortgage",
}

# Fallback when no topic is detected in the query.
GENERIC_FOLLOWUPS: list[str] = [
    "What documents do I need to apply?",
    "What are the eligibility requirements?",
    "How long does the application take?",
    "What are the interest rates?",
]

# Multi-word domain aliases, longest first for greedy matching.
_ALIASES_BY_LEN: list[str] = sorted(domain_terms.aliases(), key=len, reverse=True)


def _detected_topics(text: str) -> set[str]:
    """Canonical topics mentioned anywhere in ``text``."""
    topics: set[str] = set()
    for alias in _ALIASES_BY_LEN:
        if alias in text:
            topics.add(domain_terms.canonical_of(alias))
    lower = text.lower()
    for keyword, topic in _KEYWORD_TOPICS.items():
        if keyword in lower:
            topics.add(topic)
    return topics


def _is_answerable(conn: Connection, question: str) -> bool:
    """True if at least one active, approved chunk matches the question.

    Best-effort: a failed check never drops a candidate (returns True).
    """
    try:
        tsquery = build_tsquery(question)
        if not tsquery:
            return True
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM document_chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE c.is_active AND c.is_approved
                      AND d.is_active AND d.is_approved
                      AND c.fts @@ to_tsquery('english', %s)
                ) AS is_answerable
                """,
                (tsquery,),
            )
            # acquire() always sets row_factory=dict_row on pooled connections
            # (see db/postgres/session.py), so fetchone() returns a mapping,
            # not a tuple — indexing with [0] raises KeyError and this check
            # would silently no-op via the except below on every call.
            row = cur.fetchone()
            return bool(row["is_answerable"]) if row else True
    except Exception:
        logger.warning("Follow-up answerability check failed", exc_info=True)
        return True


def has_domain_topic(text: str) -> bool:
    """True when the text mentions any known domain topic."""
    return bool(_detected_topics(text))


def suggest_followups(
    conn: Connection,
    sub_query_texts: list[str],
    max_questions: int = 3,
) -> list[str]:
    """Suggest up to ``max_questions`` topic-appropriate follow-up questions.

    ``sub_query_texts`` are the normalized per-question search texts from
    the query plan (used only for topic detection — never echoed back).
    """
    topics: set[str] = set()
    for text in sub_query_texts:
        topics |= _detected_topics(text)

    candidates: list[str] = []
    seen: set[str] = set()
    for term in _TERM_PRIORITY:
        if term in topics and term in TOPIC_FOLLOWUPS:
            for q in TOPIC_FOLLOWUPS[term]:
                if q not in seen:
                    seen.add(q)
                    candidates.append(q)
        if len(candidates) >= max_questions:
            break

    if not candidates:
        for q in GENERIC_FOLLOWUPS:
            if q not in seen:
                seen.add(q)
                candidates.append(q)

    verified = [q for q in candidates if _is_answerable(conn, q)]
    return verified[:max_questions] or candidates[:max_questions]
