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


class TestMultiEntityPreviousTurn:
    """Regression coverage: when the previous turn named two entities, the
    subject used to be both canonicals joined ("veterans affairs down
    payment"), an incoherent mashup that -- prepended onto the *next*
    question -- verifiably broke retrieval (confidence dropped from 72.6%
    to 54.0%, flipping routing from "partial" to "no_answer"). Only the
    single most prominent entity is used now.

    Uses "What is the maximum age?" as the follow-up rather than the
    original "What are the eligibility requirements?": that question is
    now correctly recognized as self-contained (see
    TestSelfContainedFollowup below) and no longer gets any subject
    prepended at all, which would no longer exercise the single-vs-joined
    entity behavior this class is about.
    """

    HISTORY_TWO_ENTITIES = [
        {
            "question": "what is the VA funding fee with 0% down payment on first use",
            "answer": None,
        }
    ]

    def test_only_first_entity_used_as_subject(self):
        resolved = resolve_references(
            "What is the maximum age?", self.HISTORY_TWO_ENTITIES
        )
        assert resolved == "veterans affairs What is the maximum age?"
        assert "down payment" not in resolved


class TestSelfContainedFollowup:
    """Regression: a bare-looking follow-up that names its own
    self-contained information request (multi_question.is_self_contained_request)
    must not get the previous turn's subject prepended, even without a
    recognized domain ENTITY -- "eligibility requirements" isn't a
    product/program, but it's still a complete topic, not a reference
    back to whatever the previous turn was about.

    Verified live: asked right after "What documents do I need to
    apply?", "What are the eligibility requirements?" used to become
    "documents need apply What are the eligibility requirements?" (no
    clean canonical entity existed for "documents", so the fallback
    joined leftover content words into a garbled subject), and the
    answer degraded to a bare, item-less teaser sentence at 55%
    confidence instead of the DTI/eligibility content the bare question
    alone correctly retrieves.
    """

    HISTORY_DOCUMENTS = [
        {
            "question": "What documents do I need to apply?",
            "answer": "Standard underwriting documentation includes...",
        }
    ]

    def test_eligibility_requirements_untouched(self):
        assert resolve_references(
            "What are the eligibility requirements?", self.HISTORY_DOCUMENTS
        ) == "What are the eligibility requirements?"

    def test_required_documents_untouched(self):
        assert resolve_references(
            "What documents are required?", self.HISTORY_DOCUMENTS
        ) == "What documents are required?"


class TestReferentialPhrase:
    def test_the_above(self):
        resolved = resolve_references("What about the above?", HISTORY_LTM)
        assert "lifetime mortgage" in resolved
