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


def content_term_groups(question: str) -> list[set[str]]:
    """Content terms grouped so an abbreviation and its canonical expansion
    count as *one* concept, satisfied by either form, rather than several
    independently-required terms.

    A flat set (the old behavior of ``query_content_terms``, still returned
    below for callers that want that) treats "fha" -> {"fha", "federal",
    "housing", "administration"} as four separately-required terms. That's
    right for the case the expansion exists for -- the query says "dti",
    the answer spells out "debt-to-income" -- but wrong for the far more
    common reverse case: the query says "FHA" and the answer *also* says
    "FHA" (mortgage prose almost always uses the abbreviation), yet flat
    scoring marked it as missing "federal", "housing", and
    "administration", dragging a clearly on-topic answer's relevance down
    by 3/4 of that one concept for no reason (verified live: "How soon
    must I occupy a home financed with an FHA loan?" scored 0.44 relevance
    against a correct, on-topic answer, entirely because of this). Grouping
    keeps the expansion useful for its original purpose without punishing
    the reverse case: a group counts as matched if *any* member -- the
    original abbreviation or any word of its spelled-out form -- appears.
    """
    toks = re.split(r"[^a-z']+", (question or "").lower())
    groups: list[set[str]] = []
    for t in toks:
        if t in domain_terms.QUESTION_STARTERS or t in _RELEVANCE_STOP:
            continue
        # Tokens shorter than 3 chars are noise ("of", "an", stray letters)
        # *unless* they're a known domain term: "va" is only two characters
        # but it is the entire subject of "what is the minimum down payment
        # for a VA loan?". Dropping it left that query with the terms
        # {down, payment, loan} -- true of every loan program in the corpus
        # -- so nothing could distinguish the VA row from the FHA or
        # conventional ones, and relevance scoring had no signal to rank on.
        if len(t) < 3 and domain_terms.canonical_of(t) == t:
            continue
        group = {t}
        canon = domain_terms.canonical_of(t)
        if canon != t:
            group.update(
                w for w in canon.split()
                if len(w) >= 3 and w not in _RELEVANCE_STOP
            )
        groups.append(group)
    return groups


def query_content_terms(question: str) -> set[str]:
    """Significant content tokens in a question (drop starters + stopwords).

    Domain abbreviations are expanded to their canonical words so a query
    term like "dti" also matches an answer that spells out "debt-to-income".
    Returns the flat union of all term groups -- see ``content_term_groups``
    for the grouped form ``relevance_factor`` actually scores against.
    """
    terms: set[str] = set()
    for group in content_term_groups(question):
        terms.update(group)
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
    """Fraction of the query's content *concepts* present in the answer, in [0,1].

    1.0 means every significant query concept appears in the answer
    (clearly on-topic). 0.0 means none do (off-topic retrieval — the RRF
    score was inflated by common words or a wrong domain subtopic).
    Scored per term group (see ``content_term_groups``), not per flat
    term, so an abbreviation and its spelled-out expansion count as one
    concept satisfied by either form, instead of the answer needing to
    contain every word of the expansion on top of the abbreviation.
    """
    groups = content_term_groups(question)
    if not groups:
        return 1.0
    hay = (answer_text or "").lower()
    if not hay:
        return 0.0
    matched = sum(1 for group in groups if any(term_present(t, hay) for t in group))
    return matched / len(groups)
