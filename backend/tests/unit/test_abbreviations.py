"""Unit tests for doc-derived abbreviation harvesting."""

from __future__ import annotations

from app.documents.abbreviations import harvest_abbreviations


class TestHarvestAbbreviations:
    def test_full_term_first(self):
        pairs = harvest_abbreviations("A Subject Access Request (SAR) allows access.")
        assert ("sar", "subject access request") in pairs

    def test_acronym_first_colon(self):
        pairs = harvest_abbreviations("SAR: Subject Access Request is a legal right.")
        assert ("sar", "subject access request") in pairs

    def test_acronym_first_dash(self):
        pairs = harvest_abbreviations("LTV — Loan to Value is a key metric.")
        assert ("ltv", "loan to value") in pairs

    def test_no_false_positive_lowercase(self):
        assert harvest_abbreviations("what is a lifetime mortgage?") == []

    def test_skips_identical_alias_canonical(self):
        pairs = harvest_abbreviations("This is a Test (TEST).")
        assert pairs == []

    def test_multiple_pairs(self):
        pairs = harvest_abbreviations(
            "Subject Access Request (SAR) and Loan to Value (LTV) both appear."
        )
        assert ("sar", "subject access request") in pairs
        assert ("ltv", "loan to value") in pairs


class TestAcronymInitialsGate:
    """Regression: the "Full Term (ACR)" pattern captures up to ten
    preceding title-case words, which over-captures on headings. The
    document title "Down Payment and Loan-to-Value (LTV) Requirements"
    stored LTV -> "down payment and loan-to-value"; every later query
    mentioning LTV then had that whole phrase appended to its search
    text, pulling retrieval toward that one document and injecting an
    unrelated concept ("down payment"). Expansions must be
    initial-consistent with their acronym."""

    def test_heading_is_trimmed_to_the_matching_span(self):
        pairs = harvest_abbreviations(
            "Down Payment and Loan-to-Value (LTV) Requirements"
        )
        assert ("ltv", "loan-to-value") in pairs
        assert not any(c.startswith("down payment") for _, c in pairs)

    def test_hyphenated_words_contribute_each_initial(self):
        pairs = harvest_abbreviations("Combined Loan-to-Value (CLTV) limits apply.")
        assert ("cltv", "combined loan-to-value") in pairs

    def test_non_initial_expansion_is_rejected(self):
        # Nothing in "Annual Review Board" spells GDPR, so storing it would
        # corrupt every query containing that acronym.
        assert harvest_abbreviations("Annual Review Board (GDPR) applies.") == []
