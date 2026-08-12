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
