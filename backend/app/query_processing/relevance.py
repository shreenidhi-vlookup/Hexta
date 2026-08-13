"""Query<->text relevance scoring.

Shared by two call sites that both need "how well does this text answer
this question" as a plain [0, 1] score:
  - api/v1/search.py's Phase B relevance gate, which recalibrates
    confidence and can force `no_answer` for off-topic retrieval.
  - response/package_builder.py's answer-phrase selection, which uses it
    to pick the most relevant excerpt to draw the headline phrase from
    (not just whichever excerpt ranked #1 by vector/BM25 score).

Extracted out of search.py rather than package_builder.py importing from
search.py directly, which would be a circular import (search.py already
imports build_response_package from package_builder.py).
"""

from __future__ import annotations

import re

from app.query_processing import domain_terms

# Minimal stopwords dropped from a query when computing relevance. Kept
# intentionally small so meaningful domain words ("employment", "income",
# "loan", "credit", "jumbo") are preserved for overlap with the answer.
_RELEVANCE_STOP = frozenset((
    "a", "an", "the", "and", "or", "of", "for", "to", "with", "by",
    "in", "at", "on", "it", "its", "you", "your", "me", "my", "we",
    "us", "our", "them", "their", "they", "is", "are", "was", "were",
    # Auxiliary/modal verbs: grammatical scaffolding, not content — a query
    # like "...verify I have a job" was scoring "have" as a term the answer
    # had to contain, penalizing relevance for no reason.
    "have", "has", "had", "do", "does", "did", "can", "could",
    "will", "would", "should", "may", "might", "must", "i",
))


def query_content_terms(question: str) -> set[str]:
    """Significant content tokens in a question (drop starters + stopwords).

    Domain abbreviations are expanded to their canonical words so a query
    term like "dti" also matches an answer that spells out "debt-to-income".
    """
    toks = re.split(r"[^a-z']+", (question or "").lower())
    terms: set[str] = set()
    for t in toks:
        if len(t) < 3 or t in domain_terms.QUESTION_STARTERS or t in _RELEVANCE_STOP:
            continue
        terms.add(t)
        canon = domain_terms.canonical_of(t)
        if canon != t:
            terms.update(
                w for w in canon.split()
                if len(w) >= 3 and w not in _RELEVANCE_STOP
            )
    return terms


def term_stem_candidates(term: str) -> set[str]:
    """Light derivational-suffix variants of a term for matching.

    Lets morphological variants of the same root match the answer text
    ("applicant" ↔ "applications", "payment" ↔ "payments") without a full
    stemmer. Falls back to the bare term when it cannot strip a suffix.
    """
    candidates: set[str] = {term}
    if len(term) <= 3:
        return candidates
    for suffix, extra in (
        ("ies", ("y",)),
        ("tion", ("", "e")),
        ("ment", ("",)),
        ("ant", ("", "at")),
        ("ent", ("", "et")),
        ("es", ("",)),
        ("ing", ("", "e")),
        ("ed", ("", "e")),
        ("er", ("",)),
        ("or", ("",)),
        ("s", ("",)),
    ):
        if term.endswith(suffix) and len(term) > len(suffix) + 2:
            root = term[: -len(suffix)]
            candidates.update(root + e for e in extra)
    return candidates


def term_present(term: str, hay: str) -> bool:
    """Presence of a query term (and its light stems/synonyms) in the answer.

    Stems catch morphological variants ("applicant"/"application"); domain
    synonyms (domain_terms.RELEVANCE_SYNONYMS) catch semantically-identical
    but lexically-unrelated pairs a stemmer can never bridge, like
    "job"/"employment" or "verify"/"verification" -- without this, a
    correctly-retrieved paraphrase gets scored as off-topic purely because
    the answer uses different words for the same concept.
    """
    candidates = term_stem_candidates(term) | domain_terms.relevance_synonyms_of(term)
    return any(c in hay for c in candidates)


def relevance_factor(question: str, answer_text: str) -> float:
    """Fraction of the query's content terms present in the answer, in [0,1].

    1.0 means every significant query term appears in the answer (clearly
    on-topic). 0.0 means none do (off-topic retrieval — the RRF score was
    inflated by common words or a wrong domain subtopic).
    """
    terms = query_content_terms(question)
    if not terms:
        return 1.0
    hay = (answer_text or "").lower()
    if not hay:
        return 0.0
    matched = sum(1 for t in terms if term_present(t, hay))
    return matched / len(terms)
