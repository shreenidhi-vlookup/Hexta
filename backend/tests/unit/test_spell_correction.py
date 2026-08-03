"""Unit tests for spell correction module.

Covers:
- Misspelled domain terms are corrected
- Known acronyms are protected (never changed)
- Numbers, percentages, dollar amounts are never corrected
- Short tokens (<4 chars) are skipped
- Non-alpha tokens (digits, symbols, $) are skipped
- Glued word recovery (whatis → what is)
- Multi-word phrase repair (investmnt properti → investment properties)
- Regression test for infinite loop bug (credit score vs credit scores)
- Unknown words with no match are left as-is
- Empty input
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

# Ensure backend/app is importable
backend_path = Path(__file__).resolve().parent.parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.query_processing.spell_correction import correct


class TestBasicCorrection:
    """Misspelled domain terms should be corrected."""

    def test_minimum_credit_score_misspelled(self):
        result = correct("what is the minimun credt scor")
        assert "minimum" in result
        assert "score" in result

    def test_minimum_credit_score_correct(self):
        result = correct("what is the minimum credit score")
        assert result == "what is the minimum credit score"

    def test_investment_property_misspelled(self):
        result = correct("max ltv for investmnt properti")
        assert "investment" in result
        assert "properties" in result or "property" in result

    def test_documents_required_misspelled(self):
        result = correct("what documnts are requred")
        assert "documents" in result
        assert "required" in result


class TestProtectedTokens:
    """Known acronyms, numbers, and short tokens are never changed."""

    def test_acronym_ltv_not_corrected(self):
        result = correct("max ltv")
        assert "ltv" in result

    def test_acronym_fha_not_corrected(self):
        result = correct("fha loan requirements")
        assert "fha" in result

    def test_acronym_va_not_corrected(self):
        result = correct("va loan")
        assert "va" in result

    def test_acronym_dti_not_corrected(self):
        result = correct("dti ratio")
        assert "dti" in result

    def test_numbers_not_corrected(self):
        result = correct("what is 30 percent")
        assert "30" in result
        assert "percent" in result

    def test_dollar_amount_not_corrected(self):
        result = correct("house costs 500000 dollars")
        assert "500000" in result

    def test_short_tokens_not_corrected(self):
        result = correct("what is")
        assert "is" in result


class TestGluedWordRecovery:
    """Tokens like 'whatis' should be split into 'what is'."""

    def test_glued_contraction(self):
        result = correct("whatis the requirement")
        assert "what" in result
        assert "is" in result


class TestMultiwordPhraseRepair:
    """Multi-word aliases should be repaired from misspellings."""

    def test_phrase_repair_investment(self):
        result = correct("max ltv for investmnt properti")
        assert "investment" in result

    def test_phrase_repair_dti(self):
        result = correct("what is my dti ratio")
        assert "dti" in result


class TestInfiniteLoopRegression:
    """Regression tests for the infinite loop bug in _correct_multiword_phrases.

    The bug: aliases 'credit score' (singular) and 'credit scores' (plural)
    fuzzy-match each other with ratio=96 (>=92 threshold), causing the
    while-changed loop to oscillate forever.
    """

    def test_credit_score_singular_no_hang(self):
        """This specific input hung forever before the fix."""
        result = _run_with_timeout(lambda: correct("tell me the minimum credit score"), timeout=5)
        assert "credit" in result
        assert "score" in result

    def test_credit_scores_plural_no_hang(self):
        result = _run_with_timeout(lambda: correct("what are acceptable credit scores"), timeout=5)
        assert "credit" in result

    def test_credit_score_in_long_query(self):
        result = _run_with_timeout(
            lambda: correct("what is the minimum credit score for a conventional loan"),
            timeout=5,
        )
        assert "credit" in result
        assert "score" in result

    def test_multiple_singular_plural_pairs(self):
        """Ensure no oscillation with multiple singular/plural alias pairs."""
        result = _run_with_timeout(
            lambda: correct("what are the document requirements and credit scores needed"),
            timeout=5,
        )
        assert "document" in result or "documents" in result
        assert "credit" in result

    def test_max_ltvs_highest(self):
        """'max ltvs' should not oscillate between ltv/ltvs aliases."""
        result = _run_with_timeout(lambda: correct("max ltvs for conventional"), timeout=5)
        assert "ltv" in result or "loan to value" in result


class TestNoFalseCorrections:
    """Unknown words with no good match should be left as-is."""

    def test_unknown_word_left_alone(self):
        result = correct("asdfqwer zxcvbnm")
        assert result == "asdfqwer zxcvbnm"

    def test_low_confidence_not_corrected(self):
        result = correct("xyzqwerty plm")
        # Should not be 'corrected' to something unrelated
        assert "xyzqwerty" in result


class TestEmptyInput:
    def test_empty_string(self):
        assert correct("") == ""

    def test_whitespace_only(self):
        assert correct("   ") == ""


class TestIdempotency:
    """Running correct() twice should yield the same result."""

    def test_idempotent_clean(self):
        original = "what is the minimum credit score"
        once = correct(original)
        twice = correct(once)
        assert once == twice

    def test_idempotent_misspelled(self):
        original = "what is the minimun credt scor"
        once = correct(original)
        twice = correct(once)
        assert once == twice


class TestPipelineIntegration:
    """Test that correct() works as expected in the full pipeline context."""

    def test_correct_with_pipeline(self):
        """Test correct() output can be used in downstream pipeline stages."""
        from app.query_processing import pipeline

        plan = pipeline.process_query("what is the minimun credt scor")
        assert len(plan.sub_queries) == 1
        sq = plan.sub_queries[0]
        assert "minimum" in sq.text
        assert "score" in sq.text

    def test_correct_with_multi_question(self):
        """Test correct() with multi-question splitting."""
        from app.query_processing import pipeline

        plan = pipeline.process_query(
            "What documents are required, what is the maximum LTV, and also tell me the minimum credit score?"
        )
        assert len(plan.sub_queries) == 3
        # Each sub-query should be corrected
        for sq in plan.sub_queries:
            assert len(sq.text) > 0


def _run_with_timeout(func, timeout: int = 5) -> str:
    """Run a function with a timeout to detect hangs/infinite loops.

    Uses threading (cross-platform) instead of signal.SIGALRM (Unix-only).
    """
    import threading

    result = [None]
    exception = [None]

    def target():
        try:
            result[0] = func()
        except Exception as e:
            exception[0] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        raise TimeoutError(f"Function did not complete within {timeout}s — possible infinite loop")

    if exception[0] is not None:
        raise exception[0]

    return result[0]
