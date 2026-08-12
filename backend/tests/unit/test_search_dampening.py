"""Unit tests for generic bare-follow-up / off-topic confidence dampening
and mid-word fragment ranking penalty."""

from __future__ import annotations

from app.api.v1.search import (
    _apply_fragment_penalty,
    _apply_relevance_gate,
    _dampen_generic_confidence,
    _decide_routing,
    _is_bare_followup,
    _query_content_terms,
    _relevance_factor,
)
from app.ranking.rrf import RankedCandidate


class TestIsBareFollowup:
    def test_what_happens_next_is_bare(self):
        assert _is_bare_followup("what happens next")

    def test_how_does_this_work_is_bare(self):
        assert _is_bare_followup("how does this actually work")

    def test_what_does_that_mean_is_bare(self):
        assert _is_bare_followup("what does that mean")

    def test_what_is_equity_release_not_bare(self):
        assert not _is_bare_followup("what is equity release")

    def test_what_is_credit_score_not_bare(self):
        assert not _is_bare_followup("what is a credit score")

    def test_what_happens_when_someone_dies_not_bare(self):
        assert not _is_bare_followup("what happens when someone dies")

    def test_what_are_the_requirements_not_bare(self):
        assert not _is_bare_followup("what are the requirements")


class TestDampen:
    def test_bare_followup_capped(self):
        assert _dampen_generic_confidence("what happens next", "", 100.0) == 74.0

    def test_topic_question_unchanged(self):
        assert (
            _dampen_generic_confidence(
                "what is equity release",
                "Equity release lets you unlock cash from your home.",
                100.0,
            )
            == 100.0
        )

    def test_off_topic_no_token_overlap_capped(self):
        assert (
            _dampen_generic_confidence(
                "what is the weather like",
                "designed to replace lost income rather than provide one large payout",
                100.0,
            )
            == 74.0
        )

    def test_off_topic_but_answer_mentions_query_kept(self):
        assert (
            _dampen_generic_confidence(
                "how much can i borrow",
                "how much you can borrow depends on your income and affordability",
                100.0,
            )
            == 100.0
        )

    def test_low_confidence_never_raised(self):
        assert _dampen_generic_confidence("what happens next", "", 40.0) == 40.0

    def test_empty_answer_with_topic_kept(self):
        assert _dampen_generic_confidence("what is a lifetime mortgage", "", 90.0) == 90.0


class TestRelevanceGate:
    """Phase B: query↔answer relevance must recalibrate confidence so a
    wrong-topic but top-ranked chunk cannot keep a near-perfect score."""

    def test_content_terms_keep_domain_words(self):
        terms = _query_content_terms("what employment history is preferred")
        assert "employment" in terms
        assert "history" in terms
        assert "preferred" in terms
        assert "what" not in terms
        assert "is" not in terms

    def test_content_terms_jumbo(self):
        terms = _query_content_terms("what is the interest rate on jumbo loans")
        assert {"interest", "rate", "jumbo", "loans"} <= terms

    def test_content_terms_expand_abbreviation(self):
        terms = _query_content_terms("max dti")
        assert "dti" in terms
        assert "debt" in terms
        assert "income" in terms

    def test_relevance_abbreviation_matches_spelled_out_answer(self):
        assert (
            _relevance_factor(
                "max dti",
                "The debt-to-income ratio must not exceed 43% for qualified products.",
            )
            >= 0.5
        )

    def test_on_topic_factor_is_one(self):
        assert (
            _relevance_factor(
                "what employment history is preferred",
                "employment history of at least two years is preferred",
            )
            == 1.0
        )

    def test_off_topic_factor_is_zero(self):
        assert (
            _relevance_factor(
                "what employment history is preferred",
                "the deferred period is the length of time you wait before income protection payments begin",
            )
            == 0.0
        )

    def test_partial_overlap(self):
        rel = _relevance_factor(
            "what is the interest rate on jumbo loans",
            "interest rates for equity release products vary by lender and product type",
        )
        assert 0.0 < rel < 1.0

    def test_plural_tolerant(self):
        assert _relevance_factor("minimum payment", "the minimum payment is due") == 1.0

    def test_stem_tolerant_applicant_vs_applications(self):
        assert _relevance_factor("what documents does an applicant need", "applications require documents") >= 0.5

    def test_recalibrate_never_raises(self):
        assert _recalibrate_confidence_stub(100.0, 1.0) == 100.0

    def test_domain_synonym_job_employment_bridged(self):
        """Regression: "job" and "employment" mean the same thing here but
        share no stem -- relevance used to be 0.0 for this pair, which
        crushed a correctly-retrieved paraphrase's confidence below the
        no_answer floor. domain_terms.RELEVANCE_SYNONYMS bridges it."""
        rel = _relevance_factor(
            "how do lenders verify I have a job",
            "Documentation required for loan applications includes proof of "
            "income, tax returns, bank statements, and employment "
            "verification.",
        )
        assert rel > 0.0

    def test_auxiliary_verbs_not_treated_as_content_terms(self):
        """"have"/"has"/"do"/etc. are grammatical scaffolding, not content
        -- they used to count as query terms the answer had to literally
        contain, penalizing relevance for no reason."""
        terms = _query_content_terms("how do lenders verify I have a job")
        assert "have" not in terms
        assert "do" not in terms

    def test_recalibrate_keeps_high_relevance(self):
        assert _recalibrate_confidence_stub(96.9, 0.80) == 96.9

    def test_recalibrate_mild_drop_mid_relevance(self):
        conf = _recalibrate_confidence_stub(100.0, 0.5)
        assert 70.0 <= conf < 90.0

    def test_recalibrate_aggressive_drop_low_relevance(self):
        conf = _recalibrate_confidence_stub(99.2, 0.0)
        assert conf < 50.0

    def test_gate_drops_off_topic_high_confidence(self):
        conf = _apply_relevance_gate(
            "what employment history is preferred",
            "the deferred period is the length of time you wait before income protection payments begin",
            "the deferred period is the length of time you wait before income protection payments begin",
            99.2,
        )
        assert conf < 50.0

    def test_gate_keeps_on_topic_high_confidence(self):
        conf = _apply_relevance_gate(
            "what is the maximum debt to income ratio",
            "The maximum debt-to-income ratio allowed is 43%.",
            "The maximum debt-to-income ratio allowed is 43%.",
            100.0,
        )
        assert conf >= 90.0

    def test_gate_keeps_on_topic_with_morphology_miss(self):
        conf = _apply_relevance_gate(
            "what documentation is required for a loan applicant",
            "Documentation required for loan applications includes proof of income.",
            "Documentation required for loan applications includes proof of income.",
            96.9,
        )
        assert conf >= 90.0

    def test_gate_falls_back_to_top_excerpt_when_phrase_empty(self):
        conf = _apply_relevance_gate(
            "what employment history is preferred",
            "",
            "employment history of at least two years is preferred",
            90.0,
        )
        assert conf >= 90.0


class TestRoutingSafety:
    """Phase C: routing must never present an empty or off-topic phrase."""

    def test_empty_phrase_forces_no_answer(self):
        assert _decide_routing("what are the requirements", "", "some excerpt", 96.0) == "no_answer"

    def test_off_topic_low_relevance_forces_no_answer(self):
        assert (
            _decide_routing(
                "what employment history is preferred",
                "the deferred period is the length of time you wait",
                "the deferred period is the length of time you wait",
                99.2,
            )
            == "no_answer"
        )

    def test_on_topic_high_confidence_routes_answer(self):
        assert (
            _decide_routing(
                "what is the maximum debt to income ratio",
                "The maximum debt-to-income ratio allowed is 43%.",
                "The maximum debt-to-income ratio allowed is 43%.",
                100.0,
            )
            == "answer"
        )

    def test_on_topic_low_confidence_routes_no_answer(self):
        assert (
            _decide_routing(
                "what is the maximum debt to income ratio",
                "The maximum debt-to-income ratio allowed is 43%.",
                "The maximum debt-to-income ratio allowed is 43%.",
                30.0,
            )
            == "no_answer"
        )

    def test_mid_relevance_routes_partial(self):
        assert (
            _decide_routing(
                "what is the interest rate on jumbo loans",
                "interest rates for equity release products vary by lender and product type",
                "interest rates for equity release products vary by lender and product type",
                74.0,
            )
            == "partial"
        )


def _recalibrate_confidence_stub(confidence, relevance):
    from app.api.v1.search import _recalibrate_confidence

    return _recalibrate_confidence(confidence, relevance)


def _candidate(chunk_id, content, rrf_score=0.3):
    return RankedCandidate(
        chunk_id=chunk_id, content=content, document_id=1, title="Doc",
        section=None, chunk_type="paragraph", department="general",
        bm25_score=0.8, vec_score=0.8, rrf_score=rrf_score, combined_rank=1,
        is_approved=True, document_version=1,
    )


class TestFragmentPenalty:
    def test_broken_start_penalised_below_clean(self):
        ranked = [
            _candidate(1, "l mortgages with its own regulatory permissions.", rrf_score=0.5),
            _candidate(2, "Equity release allows homeowners to unlock cash.", rrf_score=0.2),
        ]
        out = _apply_fragment_penalty(ranked)
        assert out[0].chunk_id == 2  # clean chunk now first
        assert out[0].rrf_score > out[1].rrf_score

    def test_clean_chunks_unchanged(self):
        ranked = [
            _candidate(1, "Equity release allows homeowners to unlock cash.", rrf_score=0.5),
            _candidate(2, "The minimum credit score is 620.", rrf_score=0.3),
        ]
        out = _apply_fragment_penalty(ranked)
        assert out[0].chunk_id == 1
        assert out[0].rrf_score == 0.5

    def test_uppercase_fragment_footer_penalised(self):
        ranked = [
            _candidate(1, "(generated — supplementary set, not from an uploaded source document)", rrf_score=0.5),
            _candidate(2, "What is a lifetime mortgage? A: A lifetime mortgage is a loan.", rrf_score=0.2),
        ]
        out = _apply_fragment_penalty(ranked)
        assert out[0].chunk_id == 2
