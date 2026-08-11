"""Unit tests for query_processing/intent_detection.py.

No prior test file existed for this module — the two regression cases
below were only caught by running the evaluation benchmark against a
live database and diffing per-query results against the dataset's
expected_intent, not by any unit test. Added here so they can't
regress silently again.
"""

from __future__ import annotations

from app.query_processing.pipeline import process_query


def _intent(text: str) -> str:
    """Run the real pipeline (spell-correct -> normalize -> entities ->
    intent), not detect_intent() in isolation — production always
    spell-corrects and normalizes before intent detection runs, and
    skipping that step gives misleading results for misspelled input."""
    plan = process_query(text)
    return plan.sub_queries[0].intent if plan.sub_queries else "general"


class TestRequirementThresholdMetrics:
    """Regression: 'minimum X' for a qualifying-threshold metric (credit
    score, down payment) was routed to 'limits' because 'minimum' is in
    INTENT_KEYWORDS['limits'], which has higher precedence than
    'requirements'. Eval dataset ids 1 and 3 (benchmark_20260811_160932)."""

    def test_minimum_credit_score_is_requirements_not_limits(self):
        assert _intent("what is the minimum credit score") == "requirements"

    def test_minimum_credit_score_misspelled(self):
        assert _intent("what is the minimun credt scor") == "requirements"

    def test_minimum_down_payment_is_requirements(self):
        assert _intent("minimum down payment requirement") == "requirements"

    def test_maximum_ltv_still_limits(self):
        """LTV min/max wording must stay 'limits' — only the requirement-
        threshold metrics (credit score, down payment) are redirected."""
        assert _intent("what is the maximum ltv for a conventional loan") == "limits"

    def test_max_ltv_investment_property_still_limits(self):
        assert _intent("max ltv for investmnt properti") == "limits"


class TestComparisonQuestionsAreDefinition:
    """Regression: a comparison question naming two lender/program
    entities (FHA, VA) fell through to the term_type=='lender' fallback,
    which assumes any lender mention means an eligibility question. A
    comparison is asking what each thing IS, not eligibility. Eval
    dataset id 9."""

    def test_fha_vs_va_is_definition_not_eligibility(self):
        assert _intent("fha vs va loan differences") == "definition"

    def test_difference_between_phrasing(self):
        assert _intent("what is the difference between fha and va loans") == "definition"

    def test_compare_phrasing(self):
        assert _intent("compare fha and va loans") == "definition"


class TestExistingBehaviorUnchanged:
    """Non-regression: cases the benchmark already had passing."""

    def test_documents_question(self):
        assert _intent("what documnts are requred for a heloc") == "documents"

    def test_income_requirements(self):
        assert _intent("What are the income and employment requirements?") == "requirements"

    def test_down_payment_question(self):
        assert _intent("how much down payment do i need for a house") == "requirements"

    def test_empty_text_is_general(self):
        assert _intent("") == "general"

    def test_gibberish_is_general(self):
        assert _intent("asdfqwer zxcvbnm") == "general"

    def test_costs_precedence_over_limits(self):
        # APR/PMI questions should stay 'costs' even if they also contain
        # limit-ish wording.
        assert _intent("what is the apr rate") == "costs"
