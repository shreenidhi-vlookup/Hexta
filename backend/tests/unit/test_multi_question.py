"""Unit tests for multi-question splitting."""

from __future__ import annotations

from app.query_processing.multi_question import split_questions


class TestMultiQuestionSplitting:
    def test_two_questions(self):
        qs = split_questions("what is equity release? what is bridging finance?")
        assert qs == ["what is equity release", "what is bridging finance"]

    def test_three_questions(self):
        qs = split_questions(
            "what is equity release? what is bridging finance? how does a product transfer work?"
        )
        assert qs == [
            "what is equity release",
            "what is bridging finance",
            "how does a product transfer work",
        ]

    def test_five_questions(self):
        qs = split_questions(
            "what is x? what is y? what is z? how does a work? when does b happen?"
        )
        assert len(qs) == 5

    def test_questions_connected_by_and(self):
        qs = split_questions("what is x? what is y? and how does z work?")
        assert len(qs) == 3
        assert qs[-1] == "how does z work"

    def test_questions_connected_by_as_well_as(self):
        qs = split_questions(
            "what is equity release? what is bridging finance? as well as how does a product transfer work?"
        )
        assert len(qs) == 3
        assert qs[-1] == "how does a product transfer work"

    def test_questions_connected_by_then(self):
        qs = split_questions("what is equity release then how is it repaid?")
        assert qs == ["what is equity release", "how is it repaid"]

    def test_what_about_after_comma(self):
        qs = split_questions("what is equity release, what about the maximum age?")
        assert qs == ["what is equity release", "what about the maximum age"]

    def test_questions_mixed_in_paragraph(self):
        qs = split_questions(
            "i need to know what is x and what is y as well as how does z work please"
        )
        assert len(qs) >= 2

    def test_guard_keeps_list_continuation(self):
        qs = split_questions("what income is considered for later life lending")
        assert qs == ["what income is considered for later life lending"]

    def test_terse_and_joined_intents_split(self):
        qs = split_questions("max dti and required documents and first time buyer programs")
        assert qs == ["max dti", "required documents", "first time buyer programs"]

    def test_income_and_employment_requirements_stay_one(self):
        """Joint requirement list must not be split — both sides are bare
        attributes, not distinct self-contained requests."""
        qs = split_questions("income and employment requirements")
        assert qs == ["income and employment requirements"]

    def test_terse_documents_and_dti(self):
        qs = split_questions("max dti and required documents")
        assert qs == ["max dti", "required documents"]

    def test_mixed_sentence_and_terse(self):
        qs = split_questions(
            "what is the max debt to income ratio and what documents are required and eligibility"
        )
        assert "what documents are required" in qs or "required documents" in qs
        assert len(qs) >= 2
