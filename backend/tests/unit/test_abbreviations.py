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
