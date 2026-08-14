"""Answerability gate — "does this evidence actually answer the question?"

Retrieval always returns *something*. Ranking orders candidates against
each other, but never asks whether the best one is good enough to show,
so a question the knowledge base simply cannot answer still ends up with
a confident-looking answer drawn from whatever chunk ranked first: "What
is the maximum FHA loan amount?" was answered at 94% from the Discount
Points definition, purely because that definition happens to contain the
words "loan" and "amount".

The existing relevance gate (query_processing/relevance.py) cannot catch
this. It measures *lexical* overlap, and these failures are exactly the
cases where the wrong chunk shares the question's vocabulary while
answering a different question.

The cross-encoder already computes the missing signal. Unlike BM25 and
the bi-encoder -- which score query and chunk independently and can only
compare their vectors afterwards -- it reads the pair together and scores
how well the chunk responds to that specific query. Ranking already uses
it to reorder candidates; this module reuses the same number as an
absolute judgement rather than a relative one.

Calibration (evaluation/ANSWERABILITY_CALIBRATION.md), measured
over 28 answerable and 15 unanswerable queries against the glossary KB:

    answerable    min -5.91, median  7.94, max 10.79
    unanswerable  min -11.13, median -8.03, max 3.13

The distributions overlap in the middle, so this is deliberately a
*veto*, not a classifier: it only rejects scores below the worst
observed answerable query, where the evidence is affirmatively bad rather
than merely uncertain. Everything above the floor is left to the existing
confidence/relevance routing. At -6.5 the veto rejects 75% of
unanswerable queries while keeping 100% of answerable ones -- the widest
gap available with no recall cost. Raising it past -5.91 starts
discarding real answers, which is the wrong trade for a system whose
value is that its answers are trustworthy.

Being a veto also makes the failure mode safe: when the reranker is
disabled or errors, there is no score and the gate abstains, leaving
behaviour exactly as it was.
"""

from __future__ import annotations

# Cross-encoder scores below this are treated as "this chunk does not
# answer this question" regardless of how well it ranked. Configuration,
# not a constant: re-derive it with evaluation/run_benchmark.py (and the
# calibration report above) before changing it -- CLAUDE.md rule 7.
MIN_RERANK_SCORE: float = -6.5

# Confidence ceiling applied to a vetoed answer. Mirrors the scope-guard
# cap: comfortably below the "partial" floor so routing lands on
# no_answer, but non-zero so the audit log and knowledge_gaps table can
# still tell a rejected answer apart from a total retrieval miss.
VETOED_CONFIDENCE_CAP: float = 20.0


def is_answerable(rerank_score: float | None) -> bool:
    """False only when the cross-encoder affirmatively rejects the evidence.

    ``None`` (reranking disabled, failed, or the chunk was outside the
    rescored head) abstains -- an absent signal must never be read as a
    negative one.
    """
    if rerank_score is None:
        return True
    return rerank_score >= MIN_RERANK_SCORE


def cap_confidence(confidence: float, rerank_score: float | None) -> float:
    """Cap confidence for evidence the gate rejects."""
    if is_answerable(rerank_score):
        return confidence
    return min(confidence, VETOED_CONFIDENCE_CAP)
