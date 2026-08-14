"""Unit tests for response modules (package builder, validation, confidence)."""

from __future__ import annotations

from app.response.confidence_thresholds import route_by_confidence
from app.response.package_builder import (
    ResponsePackage,
    _extract_answer_phrase,
    _starts_cleanly,
    _truncate,
    build_response_package,
)
from app.response.validation import validate_package
from app.ranking.rrf import RankedCandidate


class TestConfidenceThresholds:
    def test_high_confidence_routes_to_answer(self):
        assert route_by_confidence(95.0) == "answer"

    def test_medium_confidence_routes_to_partial(self):
        assert route_by_confidence(80.0) == "partial"

    def test_low_confidence_routes_to_partial(self):
        assert route_by_confidence(60.0) == "partial"

    def test_no_answer(self):
        assert route_by_confidence(30.0) == "no_answer"

    def test_boundary_90(self):
        assert route_by_confidence(90.0) == "answer"

    def test_boundary_75(self):
        assert route_by_confidence(75.0) == "partial"

    def test_boundary_50(self):
        assert route_by_confidence(50.0) == "partial"

    def test_boundary_49(self):
        assert route_by_confidence(49.0) == "no_answer"


class TestPackageBuilder:
    def test_build_package_with_candidates(self):
        candidates = [
            RankedCandidate(
                chunk_id=1, content="The minimum credit score is 620.",
                document_id=1, title="Credit Requirements", section="Qualifications",
                chunk_type="paragraph", department="general",
                bm25_score=0.8, vec_score=0.9, rrf_score=0.05, combined_rank=1,
                is_approved=True, document_version=1,
            ),
            RankedCandidate(
                chunk_id=2, content="The maximum LTV is 80%.",
                document_id=2, title="LTV Guidelines", section="Ratios",
                chunk_type="paragraph", department="general",
                bm25_score=0.5, vec_score=0.6, rrf_score=0.03, combined_rank=2,
                is_approved=True, document_version=1,
            ),
        ]
        package = build_response_package(
            candidates=candidates,
            query_text="minimum credit score",
        )
        assert package.title == "Credit Requirements"
        assert len(package.excerpts) == 2
        assert "credit score" in package.excerpts[0].text.lower()
        assert package.response_id  # non-empty
        assert package.confidence > 0

    def test_answer_phrase_prefers_specific_over_generic_excerpt(self):
        """Regression: answer_phrase used to always come from the #1-ranked
        excerpt, even when a lower-ranked excerpt actually held the
        specific thing being asked about. A query for "0% down payment"
        used to lead with a generic framing sentence ("...varies based on
        down payment amount...") while the excerpt with the real number
        ("0% down: 2.15%") sat unused right below it. Now picks whichever
        clean-starting excerpt is most relevant to the query."""
        candidates = [
            RankedCandidate(
                chunk_id=1,
                content=(
                    "The VA funding fee varies based on down payment amount, "
                    "whether the loan is a first or subsequent use of VA "
                    "benefits, and whether the borrower is a veteran."
                ),
                document_id=1, title="VA Guide", section=None, chunk_type="paragraph",
                department="general", bm25_score=0.9, vec_score=0.9,
                rrf_score=0.06, combined_rank=1,
                is_approved=True, document_version=1,
            ),
            RankedCandidate(
                chunk_id=2,
                content="0% down payment: 2.15% funding fee on first use.",
                document_id=1, title="VA Guide", section=None, chunk_type="paragraph",
                department="general", bm25_score=0.5, vec_score=0.7,
                rrf_score=0.04, combined_rank=2,
                is_approved=True, document_version=1,
            ),
        ]
        package = build_response_package(
            candidates=candidates,
            query_text="what is the VA funding fee with 0% down payment on first use",
        )
        assert "2.15%" in package.answer_phrase

    def test_answer_phrase_ties_keep_rank_order(self):
        """When relevance doesn't differentiate between excerpts (the
        common case), phrase selection must still default to the
        top-ranked excerpt -- this change should only matter when
        relevance actually varies."""
        candidates = [
            RankedCandidate(
                chunk_id=1, content="The minimum credit score is 620.",
                document_id=1, title="Credit", section=None, chunk_type="paragraph",
                department="general", bm25_score=0.8, vec_score=0.9,
                rrf_score=0.05, combined_rank=1,
                is_approved=True, document_version=1,
            ),
            RankedCandidate(
                chunk_id=2, content="The maximum LTV is 80%.",
                document_id=2, title="LTV", section=None, chunk_type="paragraph",
                department="general", bm25_score=0.5, vec_score=0.6,
                rrf_score=0.03, combined_rank=2,
                is_approved=True, document_version=1,
            ),
        ]
        package = build_response_package(
            candidates=candidates,
            query_text="tell me about mortgages",
        )
        assert package.answer_phrase == "The minimum credit score is 620."

    def test_answer_phrase_prefers_complete_item_over_teaser_on_tie(self):
        """Regression: a checklist item that carries its parent sentence as
        context (checklist_chunker.py) has the same relevance as that
        parent excerpt on its own, since the item's text is literally
        "preamble + bullet". Rank order alone would then pick the bare
        preamble -- a teaser ending in ":" that promises a list without
        delivering one ("...following categories:") -- over the excerpt
        one rank down that actually has an item from that list."""
        candidates = [
            RankedCandidate(
                chunk_id=1,
                content=(
                    "Eligibility for a VA-backed loan depends on military "
                    "service history, and applicants generally fall into "
                    "one of the following categories:"
                ),
                document_id=1, title="VA Guide", section=None, chunk_type="paragraph",
                department="general", bm25_score=1.0, vec_score=0.86,
                rrf_score=0.06, combined_rank=1,
                is_approved=True, document_version=1,
            ),
            RankedCandidate(
                chunk_id=2,
                content=(
                    "Eligibility for a VA-backed loan depends on military "
                    "service history, and applicants generally fall into "
                    "one of the following categories: Veterans who served "
                    "the minimum active-duty service requirement."
                ),
                document_id=1, title="VA Guide", section=None, chunk_type="checklist",
                department="general", bm25_score=0.9, vec_score=0.71,
                rrf_score=0.05, combined_rank=2,
                is_approved=True, document_version=1,
            ),
        ]
        package = build_response_package(
            candidates=candidates,
            query_text="who is eligible for a VA loan",
        )
        assert "Veterans who served" in package.answer_phrase

    def test_table_excerpt_gets_verbatim_answer_phrase(self):
        """Regression: a table excerpt used to always get answer_phrase ""
        (its short rows have no terminal punctuation, so
        _extract_answer_phrase's prose-oriented heading check rejected
        every line), which made search.py's _decide_routing() force
        no_answer regardless of confidence -- discarding a correctly
        retrieved, high-confidence table answer entirely. Live-verified:
        an LTV-limits table at 98.4% confidence surfaced "No answer
        found" before this fix."""
        candidates = [
            RankedCandidate(
                chunk_id=1,
                content=(
                    "Property Type       Max LTV   Min Down Payment\n"
                    "Primary Residence    97%        3%\n"
                    "Investment Property  85%        15%"
                ),
                document_id=1, title="LTV Policy", section=None, chunk_type="table",
                department="general", bm25_score=0.8, vec_score=0.9,
                rrf_score=0.05, combined_rank=1,
                is_approved=True, document_version=1,
            ),
        ]
        package = build_response_package(
            candidates=candidates,
            query_text="what is the max ltv for investment property",
        )
        assert package.answer_phrase != ""
        assert "Investment Property" in package.answer_phrase

    def test_build_package_empty_candidates(self):
        package = build_response_package(
            candidates=[],
            query_text="nonexistent",
        )
        assert package.title == "No Results Found"
        assert len(package.excerpts) == 0
        assert package.confidence == 0.0

    def test_build_package_truncates_long_content(self):
        long_text = "x" * 1000
        candidates = [
            RankedCandidate(
                chunk_id=1, content=long_text,
                document_id=1, title="Doc", section=None, chunk_type="paragraph",
                department="general", bm25_score=0.9, vec_score=0.9,
                rrf_score=0.05, combined_rank=1,
                is_approved=True, document_version=1,
            ),
        ]
        package = build_response_package(
            candidates=candidates,
            query_text="test",
        )
        assert len(package.excerpts[0].text) <= 600


class TestPhraseExtraction:
    """answer_phrase extraction: complete sentences, no mid-word cuts,
    no tiny chunk-boundary fragments."""

    def test_prefers_first_substantive_sentence(self):
        text = "The minimum credit score required is 620. Borrowers must also meet income thresholds."
        assert "620" in _extract_answer_phrase(text)

    def test_skips_tiny_fragment(self):
        text = "ents. The loan requires a minimum credit score of 620. More details follow."
        phrase = _extract_answer_phrase(text)
        assert "ents." not in phrase
        assert "620" in phrase

    def test_skips_generated_footer(self):
        text = "Source: Some_QA (generated) | Category: Lending. Equity release requires separate FCA authorisation."
        phrase = _extract_answer_phrase(text)
        assert "Source:" not in phrase
        assert "FCA" in phrase

    def test_truncates_long_sentence_at_word_boundary(self):
        text = "Interest is charged on the outstanding balance usually after a deferred period of up to three months."
        phrase = _extract_answer_phrase(text, max_chars=40)
        assert phrase.endswith("…")
        assert len(phrase) <= 41
        last_word = phrase[:-1].rsplit(" ", 1)[-1]
        assert last_word.isalpha()  # never ends mid-word

    def test_empty_input(self):
        assert _extract_answer_phrase("") == ""

    def test_short_phrase_falls_back(self):
        phrase = _extract_answer_phrase("Yes.")
        assert phrase == "Yes."


class TestPhraseQuality:
    """answer_phrase must never be a question, a heading, or a fragment."""

    def test_rejects_question_sentence(self):
        assert _extract_answer_phrase("What is the deferred period?") == ""

    def test_rejects_question_then_keeps_statement(self):
        phrase = _extract_answer_phrase(
            "What is the deferred period? Deferred periods typically run from 1 to 12 months."
        )
        assert "deferred periods typically run" in phrase.lower()

    def test_rejects_heading_only(self):
        assert _extract_answer_phrase("Credit Score Requirements") == ""

    def test_rejects_heading_and_keeps_statement(self):
        phrase = _extract_answer_phrase(
            "Credit Score Requirements\nMinimum credit score requirements vary by loan product."
        )
        assert phrase == "Minimum credit score requirements vary by loan product."

    def test_strips_leading_heading_line(self):
        phrase = _extract_answer_phrase(
            "Income Documentation\nApplicants must provide proof of income for the last three months."
        )
        assert phrase.startswith("Applicants")
        assert "Income Documentation" not in phrase

    def test_rejects_heading_that_is_a_question(self):
        assert _extract_answer_phrase("What are the interest rates") == ""

    def test_empty_when_all_questions(self):
        assert _extract_answer_phrase("What is it? How does it work?") == ""


class TestStartsCleanly:
    def test_uppercase_start(self):
        assert _starts_cleanly("Equity release lets you unlock cash.")

    def test_digit_start(self):
        assert _starts_cleanly("620 is the minimum score.")

    def test_mid_word_fragment(self):
        assert not _starts_cleanly("l mortgages with its own regulatory permissions")

    def test_lowercase_word_start(self):
        assert not _starts_cleanly("ents. Source: Some doc")

    def test_empty(self):
        assert not _starts_cleanly("   ")


class TestCleanExcerptSelection:
    """The answer_phrase must come from a cleanly-starting excerpt, so a
    mid-word chunk-boundary fragment never opens the answer."""

    def _candidate(self, chunk_id, content, title="Doc"):
        return RankedCandidate(
            chunk_id=chunk_id, content=content, document_id=1, title=title,
            section=None, chunk_type="paragraph", department="general",
            bm25_score=0.8, vec_score=0.8, rrf_score=0.3, combined_rank=1,
            is_approved=True, document_version=1,
        )

    def test_skips_broken_top_excerpt(self):
        package = build_response_package(
            candidates=[
                self._candidate(1, "l mortgages with its own regulatory permissions. Second sentence."),
                self._candidate(2, "Equity release allows homeowners to unlock cash from their home."),
            ],
            query_text="equity release",
        )
        assert package.answer_phrase.startswith("Equity release")

    def test_keeps_clean_top_excerpt(self):
        package = build_response_package(
            candidates=[self._candidate(1, "Equity release allows homeowners to unlock cash.")],
            query_text="equity release",
        )
        assert package.answer_phrase.startswith("Equity release")

    def test_all_broken_falls_back_to_top(self):
        package = build_response_package(
            candidates=[self._candidate(1, "l mortgages with its own regulatory permissions.")],
            query_text="equity release",
        )
        assert package.answer_phrase  # non-empty fallback

    def test_question_only_top_chunk_yields_empty_phrase(self):
        """A top chunk that is only a question must not surface as an answer."""
        package = build_response_package(
            candidates=[self._candidate(1, "What is the deferred period?")],
            query_text="deferred period",
        )
        assert package.answer_phrase == ""

    def test_heading_only_top_chunk_yields_empty_phrase(self):
        """A top chunk that is only a heading must not surface as an answer."""
        package = build_response_package(
            candidates=[self._candidate(1, "Credit Score Requirements")],
            query_text="credit score",
        )
        assert package.answer_phrase == ""

    def test_heading_only_top_falls_through_to_next_excerpt(self):
        """Regression: a bare section heading with no body can rank #1 --
        it repeats the query's own words -- and used to make the whole
        response come back with answer_phrase="" even when a lower-ranked
        excerpt had a real, complete answer. Live-verified: "what is a
        manufactured home" hit exactly this, top excerpt "Manufactured
        Home Additional Requirements" (99.2% confidence, just a heading),
        second excerpt the actual definition (98.4%) -- surfaced "No
        answer found" despite the definition sitting right there."""
        package = build_response_package(
            candidates=[
                self._candidate(1, "Manufactured Home Additional Requirements"),
                self._candidate(
                    2,
                    "Manufactured homes must be titled as real property and "
                    "permanently affixed to an approved foundation.",
                ),
            ],
            query_text="what is a manufactured home",
        )
        assert package.answer_phrase.startswith("Manufactured homes must")

    def test_checklist_item_without_punctuation_gets_verbatim_phrase(self):
        """Regression: checklist items rarely end in a period ("- Two-to-
        four unit properties when the borrower occupies one unit"), so
        _extract_answer_phrase's heading check ("no terminal punctuation
        + short") misclassified them as headings too, the same failure
        mode as tables. Verified live at 99.2% confidence surfacing "No
        answer found". Checklist items are now handled like tables:
        verbatim text, no prose sentence-extraction."""
        candidate = RankedCandidate(
            chunk_id=1,
            content="- Two-to-four unit properties when the borrower occupies one unit",
            document_id=1, title="Doc", section=None, chunk_type="checklist",
            department="general", bm25_score=0.9, vec_score=0.9,
            rrf_score=0.3, combined_rank=1, is_approved=True, document_version=1,
        )
        package = build_response_package(
            candidates=[candidate],
            query_text="can a two to four unit property be financed",
        )
        assert package.answer_phrase == "- Two-to-four unit properties when the borrower occupies one unit"


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("short text", 100) == "short text"

    def test_long_text_cut_at_word_boundary(self):
        out = _truncate("hello world foo bar baz", 10)
        assert out.endswith("…")
        last_word = out[:-1].rsplit(" ", 1)[-1]
        assert last_word.isalpha()

    def test_len_within_limit(self):
        out = _truncate("a" * 100 + " b" * 100, 30)
        assert len(out) <= 30


class TestValidation:
    def test_validate_high_confidence_passes(self):
        package = ResponsePackage(
            response_id="test",
            title="Test",
            confidence=95.0,
            routing="answer",
        )
        valid, reason = validate_package(package, user=None)
        assert valid is True
        assert reason == "OK"

    def test_validate_low_confidence_passes(self):
        """Low confidence is handled by route_by_confidence, not validation.

        A confidence of 30% should set routing to 'no_answer' but validation
        must still pass — the package is returned to the user as a graceful
        'no_answer' response, not a 500 error.
        """
        package = ResponsePackage(
            response_id="test",
            title="Test",
            confidence=30.0,
            routing="no_answer",
        )
        valid, reason = validate_package(package, user=None)
        assert valid is True
        assert reason == "OK"

    def test_validate_zero_confidence_passes(self):
        """Zero confidence (no results found) must not cause a 500.

        This is the 'Confidence 0.0% below threshold' bug — validation
        used to reject zero-confidence packages, causing a 500 error
        instead of a graceful 'no_answer' response.
        """
        package = ResponsePackage(
            response_id="test",
            title="No Results Found",
            confidence=0.0,
            routing="no_answer",
        )
        valid, reason = validate_package(package, user=None)
        assert valid is True
        assert reason == "OK"

    def test_validate_admin_bypasses_rbac(self):
        from app.response.package_builder import Excerpt, Source

        excerpt = Excerpt(
            text="content",
            source=Source(
                chunk_id=1,
                document_id=1,
                title="Doc",
                section=None,
                chunk_type="paragraph",
                department="general",
                is_approved=True,
                document_version=1,
            ),
            confidence=90.0, bm25_score=0.9, vec_score=0.9,
        )
        package = ResponsePackage(
            response_id="test",
            title="Test",
            excerpts=[excerpt],
            confidence=90.0,
            routing="answer",
        )
        user = {"role": "super_admin", "department": "general", "allowed_departments": []}
        valid, _ = validate_package(package, user)
        assert valid is True

    def test_validate_unapproved_chunk_fails(self):
        from app.response.package_builder import Excerpt, Source

        excerpt = Excerpt(
            text="content",
            source=Source(
                chunk_id=1,
                document_id=1,
                title="Doc",
                section=None,
                chunk_type="paragraph",
                department="general",
                is_approved=False,
                document_version=1,
            ),
            confidence=90.0, bm25_score=0.9, vec_score=0.9,
        )
        package = ResponsePackage(
            response_id="test",
            title="Test",
            excerpts=[excerpt],
            confidence=90.0,
            routing="answer",
        )
        valid, reason = validate_package(package, user=None)
        assert valid is False
        assert "not approved" in reason

