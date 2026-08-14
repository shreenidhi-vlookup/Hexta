"""Unit tests for the cross-encoder answerability gate.

Covers the contract that matters for safety: the gate rejects only
affirmatively-bad evidence, and abstains whenever it has no signal --
an absent score must never be read as a negative one, or disabling the
reranker would silently turn every answer into "no answer".
"""

from __future__ import annotations

import pytest

from app.api.v1.search import _decide_routing
from app.response import answerability


class TestIsAnswerable:
    def test_rejects_scores_below_the_floor(self):
        assert answerability.is_answerable(-9.34) is False

    def test_accepts_scores_at_and_above_the_floor(self):
        assert answerability.is_answerable(answerability.MIN_RERANK_SCORE) is True
        assert answerability.is_answerable(10.79) is True

    def test_abstains_without_a_score(self):
        """Reranker disabled or failed -> behave exactly as before."""
        assert answerability.is_answerable(None) is True

    def test_floor_sits_below_worst_measured_answerable_query(self):
        """Calibration guard: the worst answerable query in the eval set
        scored -5.91. A floor above that would discard real answers."""
        assert answerability.MIN_RERANK_SCORE < -5.91


class TestCapConfidence:
    def test_vetoed_confidence_is_capped(self):
        assert answerability.cap_confidence(94.0, -9.34) == (
            answerability.VETOED_CONFIDENCE_CAP
        )

    def test_accepted_confidence_untouched(self):
        assert answerability.cap_confidence(94.0, 8.06) == 94.0

    def test_cap_never_raises_confidence(self):
        assert answerability.cap_confidence(5.0, -9.34) == 5.0

    def test_cap_lands_below_the_partial_floor(self):
        """Otherwise a vetoed answer would still route as an answer."""
        from app.response.confidence_thresholds import route_by_confidence

        assert route_by_confidence(answerability.VETOED_CONFIDENCE_CAP) == "no_answer"


class TestRoutingIntegration:
    # The real chunk that produced the failure. It has to contain the
    # question's words ("loan", "amount") for the lexical gate to pass it
    # -- that is precisely the blind spot this gate exists to cover.
    ON_TOPIC = (
        "Points (Discount Points): Optional upfront fees paid at closing to "
        "reduce the interest rate on a loan, with one point typically equal "
        "to 1% of the loan amount."
    )

    def test_lexically_relevant_but_unanswered_is_rejected(self):
        """The exact failure: 'What is the maximum FHA loan amount?' was
        answered at 94% from the Discount Points definition because that
        text contains 'loan' and 'amount'."""
        routing = _decide_routing(
            "What is the maximum FHA loan amount?",
            self.ON_TOPIC, self.ON_TOPIC, 94.0, -6.76,
        )
        assert routing == "no_answer"

    def test_same_evidence_without_score_keeps_old_behaviour(self):
        routing = _decide_routing(
            "What is the maximum FHA loan amount?",
            self.ON_TOPIC, self.ON_TOPIC, 94.0, None,
        )
        assert routing != "no_answer"

    def test_good_answer_survives_the_gate(self):
        text = "Equity: The difference between a property's current market value."
        assert _decide_routing("What is equity?", text, text, 96.0, 8.06) == "answer"
