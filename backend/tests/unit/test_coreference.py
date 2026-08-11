"""Unit tests for conversation coreference resolution."""

from __future__ import annotations

from app.query_processing.coreference import resolve_references

HISTORY_LTM = [{"question": "What is a lifetime mortgage?", "answer": "A loan for life..."}]
HISTORY_GUARANTOR = [{"question": "What is a guarantor?", "answer": "Someone who..."}]
HISTORY_NONE = []


class TestPronounResolution:
    def test_leading_pronoun(self):
        assert resolve_references("How is it repaid?", HISTORY_LTM) == (
            "How is lifetime mortgage repaid?"
        )

    def test_they_reference(self):
        assert resolve_references("Can they be removed later?", HISTORY_GUARANTOR) == (
            "Can guarantor be removed later?"
        )

    def test_what_about_it(self):
        assert resolve_references("What about it?", HISTORY_LTM) == (
            "What about lifetime mortgage?"
        )

    def test_no_history_no_change(self):
        assert resolve_references("How is it repaid?", HISTORY_NONE) == "How is it repaid?"

    def test_subject_already_present_no_change(self):
        assert resolve_references("How is a lifetime mortgage repaid?", HISTORY_LTM) == (
            "How is a lifetime mortgage repaid?"
        )


class TestBareFollowup:
    def test_bare_risks_question(self):
        resolved = resolve_references("What are the risks?", HISTORY_LTM)
        assert resolved == "lifetime mortgage What are the risks?"

    def test_bare_what_happens_next(self):
        resolved = resolve_references("What happens next?", HISTORY_LTM)
        assert "lifetime mortgage" in resolved

    def test_topic_question_untouched(self):
        # A short question that already names a domain topic must not be
        # polluted with the previous turn's subject.
        assert resolve_references("What is a credit score?", HISTORY_LTM) == (
            "What is a credit score?"
        )

    def test_bare_followup_still_resolves(self):
        assert resolve_references("What is the maximum age?", HISTORY_LTM) == (
            "lifetime mortgage What is the maximum age?"
        )

    def test_proper_noun_topic_untouched(self):
        # A capitalized proper noun (France) means the question names its own
        # subject even though it is not a domain topic.
        assert resolve_references("What is the capital of France?", HISTORY_LTM) == (
            "What is the capital of France?"
        )


class TestReferentialPhrase:
    def test_the_above(self):
        resolved = resolve_references("What about the above?", HISTORY_LTM)
        assert "lifetime mortgage" in resolved
