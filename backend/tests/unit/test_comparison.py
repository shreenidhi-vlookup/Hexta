"""Unit tests for comparison-question detection and operand extraction."""

from __future__ import annotations

from app.query_processing.comparison import extract_comparison_operands, is_comparison


class TestComparisonDetection:
    def test_difference_between(self):
        assert extract_comparison_operands(
            "what is the difference between critical illness and income protection?"
        ) == ("critical illness", "income protection")

    def test_compare_x_and_y(self):
        assert extract_comparison_operands(
            "compare fixed rate and adjustable rate mortgages"
        ) == ("fixed rate", "adjustable rate mortgages")

    def test_how_is_x_different_from_y(self):
        assert extract_comparison_operands(
            "how is a lifetime mortgage different from a standard mortgage?"
        ) == ("a lifetime mortgage", "a standard mortgage")

    def test_vs_form(self):
        assert extract_comparison_operands("fha vs conventional") == ("fha", "conventional")

    def test_which_is_better(self):
        assert extract_comparison_operands(
            "equity release or home reversion which is better?"
        ) == ("equity release", "home reversion")

    def test_non_comparison_returns_none(self):
        assert extract_comparison_operands("what is a lifetime mortgage?") is None
        assert extract_comparison_operands("what are the documents required?") is None
        assert extract_comparison_operands("") is None

    def test_is_comparison_flag(self):
        assert is_comparison("compare x and y")
        assert not is_comparison("what is x")

    def test_operands_never_equal(self):
        assert extract_comparison_operands("compare x and x") is None


class TestSharedQualifierDistribution:
    """A trailing qualifier on one operand ("VA down payment") that
    clearly belongs to both sides of the comparison must be copied onto
    a bare program name on the other side, not left applying to only the
    operand it happened to sit next to."""

    def test_vs_form_distributes_trailing_qualifier(self):
        assert extract_comparison_operands("fha vs va down payment") == (
            "fha down payment",
            "va down payment",
        )

    def test_compare_form_distributes_trailing_qualifier(self):
        assert extract_comparison_operands(
            "compare fha and conventional minimum credit scores"
        ) == ("fha minimum credit scores", "conventional minimum credit scores")

    def test_qualifier_on_left_distributes_to_bare_right(self):
        assert extract_comparison_operands("fha down payment vs va") == (
            "fha down payment",
            "va down payment",
        )

    def test_no_distribution_when_neither_side_is_a_bare_program(self):
        # Both sides already fully specified -- nothing to distribute.
        assert extract_comparison_operands(
            "fixed rate vs adjustable rate mortgages"
        ) == ("fixed rate", "adjustable rate mortgages")

    def test_no_distribution_when_qualified_side_lacks_a_program_prefix(self):
        # "conventional" side has no qualifier of its own to project, and
        # the bare side ("dti") isn't a program name, so this must not
        # trigger the fallback at all.
        assert extract_comparison_operands(
            "compare dti and conventional underwriting guidelines"
        ) == ("dti", "conventional underwriting guidelines")


class TestComparisonSurvivesQueryProcessing:
    """process_query must not let multi_question's "and" boundary split a
    comparison question into two unrelated single-topic searches before
    comparison detection ever runs -- "difference between X and Y" and
    "compare X and Y" both use "and" as their own connector."""

    def test_difference_between_stays_one_sub_query(self):
        from app.query_processing.pipeline import process_query

        plan = process_query("difference between PMI and MIP")  # raw input, pipeline lowercases
        assert len(plan.sub_queries) == 1

    def test_compare_form_stays_one_sub_query(self):
        from app.query_processing.pipeline import process_query

        plan = process_query("compare fha and conventional minimum credit scores")
        assert len(plan.sub_queries) == 1

    def test_ordinary_multi_question_still_splits(self):
        from app.query_processing.pipeline import process_query

        plan = process_query("What is the minimum credit score and what is the maximum DTI?")
        assert len(plan.sub_queries) == 2
