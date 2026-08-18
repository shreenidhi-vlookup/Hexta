"""Unit tests for response/package_builder.py's answer-phrase extraction.

Regression coverage for a real bug chain found via a live manual-upload
test: structural_chunker's min_tokens merge (see test_chunking.py) can
legitimately produce a multi-line chunk joining a title/heading/"Note:"
label with the real lead sentence, separated by "\\n". Two bugs combined
to turn that into an empty answer_phrase:

1. _SENTENCE_RE only split on ".!?" + whitespace, never on newlines, so
   the whole multi-line blob was treated as a single "sentence" candidate.
2. _is_heading() treated *any* line not ending in ".!?" as a heading --
   including a genuine, long sentence that happens to introduce a list
   and so ends in ":" ("Required documents include the following
   items...before final approval:"). That candidate got rejected as "just
   a heading", leaving no usable answer phrase at all.

An empty answer_phrase makes search.py's _decide_routing() force
`no_answer` regardless of confidence -- so this wasn't just a cosmetic
issue, it silently turned a well-retrieved, high-confidence excerpt into
"No answer found" in the UI.
"""

from __future__ import annotations

from app.response.package_builder import _extract_answer_phrase, _is_heading


class TestIsHeading:
    def test_short_line_no_terminal_punct_is_heading(self):
        assert _is_heading("Credit Score Requirements")

    def test_short_colon_label_is_heading(self):
        assert _is_heading("Note:")

    def test_period_terminated_sentence_not_heading(self):
        assert not _is_heading("The minimum credit score is 620.")

    def test_long_colon_terminated_sentence_not_heading(self):
        """The core regression: a genuine sentence introducing a list
        must not be misclassified just because it ends in ':' instead
        of '.'/'!'/'?'."""
        sentence = (
            "Required documents for confirming an applicant's employment "
            "status include the following items, all of which must be "
            "submitted before the loan can move to final approval:"
        )
        assert len(sentence) > 80
        assert not _is_heading(sentence)

    def test_empty_string_not_heading(self):
        assert not _is_heading("")


class TestExtractAnswerPhraseMultilineChunk:
    def test_merged_heading_plus_colon_sentence_yields_the_sentence(self):
        content = (
            "Residential Mortgage Underwriting Policy — Employment and "
            "Income Verification\n"
            "Employment Documentation Requirements\n"
            "Note:\n"
            "Required documents for confirming an applicant's employment "
            "status include the following items, all of which must be "
            "submitted before the loan can move to final approval:"
        )
        phrase = _extract_answer_phrase(content)
        assert phrase.startswith("Required documents for confirming")
        assert phrase != ""

    def test_all_headings_no_sentence_yields_empty(self):
        content = "Title Line\nAnother Header\nNote:"
        assert _extract_answer_phrase(content) == ""

    def test_single_clean_sentence_unaffected(self):
        content = "Credit scores are a key factor in determining loan eligibility."
        assert _extract_answer_phrase(content) == content


class TestExtractAnswerPhraseWrappedProse:
    """Found live via manual upload testing: a plain definition chunk whose
    source text was hard-wrapped at ~75 columns lost its own lead fact.

    "Rate Lock Window: A client may lock a rate up to 6 months before their
    current deal ends, giving time to compare products without losing the
    option to switch lenders if a better rate appears later." is one
    logical sentence, but the chunk stores it with the source's original
    line-wrap newlines intact. _strip_leading_heading saw the first wrapped
    line (70 chars, no terminal punctuation) and dropped it whole as if it
    were a section heading -- but that line is the one holding "6 months",
    the fact "How long before a deal ends can a client lock a rate?" is
    actually asking for. What survived was only the tail two fragments,
    neither of which answers the question.

    Distinguishing a real heading/label line (this repo's existing merged-
    heading test above) from a mid-sentence line-wrap: a wrapped
    continuation line starts with a lowercase word and the line before it
    doesn't end in terminal punctuation, whereas a genuine heading/label
    line is capitalized. That's the signal the fix relies on -- it must
    not regress the merged-heading case, which depends on capitalized
    lines staying split.
    """

    def test_wrapped_definition_keeps_its_lead_fact(self):
        content = (
            "Rate Lock Window: A client may lock a rate up to 6 months before their\n"
            "current deal ends, giving time to compare products without losing the\n"
            "option to switch lenders if a better rate appears later."
        )
        phrase = _extract_answer_phrase(content, query_text="How long before a deal ends can a client lock a rate?")
        assert "6 months" in phrase

    def test_wrapped_erc_definition_keeps_its_lead_fact(self):
        content = (
            "Early Repayment Charge (ERC): A fee charged by the current lender if the\n"
            "client repays or switches away from their mortgage before the end of the\n"
            "agreed deal period, usually calculated as a percentage of the outstanding\n"
            "balance."
        )
        phrase = _extract_answer_phrase(content, query_text="What is an Early Repayment Charge?")
        # The fact itself ("a fee charged by the current lender") must
        # survive -- that's what the old bug dropped by treating the first
        # wrapped line as a heading. The 200-char cap legitimately clips
        # the tail ("...balance.") off a sentence this long; that's plain
        # truncation, not the defect under test.
        assert phrase.startswith("Early Repayment Charge")
        assert "fee charged by the current lender" in phrase

    def test_merged_heading_case_still_splits_on_real_boundaries(self):
        """The existing heading-merge regression (capitalized label lines)
        must not be swallowed by the wrapped-line join."""
        content = (
            "Residential Mortgage Underwriting Policy — Employment and "
            "Income Verification\n"
            "Employment Documentation Requirements\n"
            "Note:\n"
            "Required documents for confirming an applicant's employment "
            "status include the following items, all of which must be "
            "submitted before the loan can move to final approval:"
        )
        phrase = _extract_answer_phrase(content)
        assert phrase.startswith("Required documents for confirming")
