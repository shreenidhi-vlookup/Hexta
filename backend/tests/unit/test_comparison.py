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
