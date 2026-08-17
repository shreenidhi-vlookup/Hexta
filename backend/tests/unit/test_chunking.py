"""Unit tests for document chunking (structural_chunker, checklist_chunker).

Regression coverage for two bugs found during retrieval-accuracy work:

1. StructuralChunker declared ``min_tokens`` but never enforced it — any
   undersized paragraph chunk (a stray one-liner, a trailing sentence
   fragment) was emitted standalone, producing a low-signal embedding
   and a weak BM25 document.
2. chunk_checklist() mislabeled the non-list preamble preceding the first
   bullet in a mixed block as ``chunk_type="checklist"`` instead of
   ``"paragraph"``, hiding it from paragraph-only downstream logic (like
   fix #1's merge pass).
"""

from __future__ import annotations

from app.documents.chunking.checklist_chunker import chunk_checklist
from app.documents.chunking.structural_chunker import Chunk, StructuralChunker
from app.documents.text_extraction import ExtractedText


class TestTableDetection:
    """Regression coverage for a real-world failure found via manual
    upload testing: a plain-text table with multi-word cell values
    ("Property Type", "Investment Property") was silently swallowed into
    the surrounding paragraph instead of being kept as an atomic table
    chunk, because _is_table_block used to split each line on *any*
    whitespace -- multi-word cells made the per-row word count diverge
    even though the column count was identical."""

    def _chunker(self):
        return StructuralChunker()

    def test_multiword_cells_detected_as_table(self):
        table_text = (
            "Property Type       Max LTV   Min Down Payment\n"
            "Primary Residence    97%        3%\n"
            "Second Home          90%        10%\n"
            "Investment Property  85%        15%"
        )
        assert self._chunker()._is_table_block(table_text)

    def test_table_survives_full_pipeline_as_atomic_chunk(self):
        text = (
            "Loan-to-Value Limits by Property Type\n\n"
            "Property Type       Max LTV   Min Down Payment\n"
            "Primary Residence    97%        3%\n"
            "Second Home          90%        10%\n"
            "Investment Property  85%        15%\n\n"
            "Closing costs are itemized separately."
        )
        extracted = ExtractedText(text=text, pages=[text], source_format="txt")
        chunks = list(self._chunker().chunk(extracted))
        table_chunks = [c for c in chunks if c.chunk_type == "table"]
        assert len(table_chunks) == 1
        assert "Investment Property" in table_chunks[0].content
        assert "Primary Residence" in table_chunks[0].content

    def test_single_word_cell_table_still_detected(self):
        # Single-word cells, column-aligned with the same 2+-space
        # convention real plain-text tables use.
        table_text = "a    b    c\nd    e    f\ng    h    i"
        assert self._chunker()._is_table_block(table_text)

    def test_single_space_table_still_detected_via_fallback(self):
        # Pre-existing behavior (test_documents.py::test_chunk_preserves_tables)
        # relies on single-space, single-word-cell tables ("col1 col2 col3")
        # still being detected -- kept as a fallback when the stronger
        # 2+-space column signal isn't present.
        assert self._chunker()._is_table_block("a b c\nd e f\ng h i")

    def test_prose_not_misdetected_as_table(self):
        prose = (
            "This is a normal paragraph about mortgage underwriting.\n"
            "It has several sentences describing the process in detail."
        )
        assert not self._chunker()._is_table_block(prose)


class TestChecklistPreambleLabel:
    def test_short_list_keeps_its_preamble_in_one_unit(self):
        """Superseded expectation: this used to assert one chunk per item.
        A list of two-or-three-word items is one retrieval unit, because
        fragments that small outrank real content on BM25 (which
        normalises by length) while carrying almost no meaning. See
        TestShortListsStayWhole for the measurement. What this class was
        really guarding -- the preamble not being lost or mislabelled --
        still holds."""
        text = "Required documents for your application:\n- Pay stubs\n- Bank statements"
        chunks = list(chunk_checklist(text))
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "checklist"
        assert "Required documents for your application:" in chunks[0].content
        assert "Pay stubs" in chunks[0].content
        assert "Bank statements" in chunks[0].content

    def test_no_list_items_yields_nothing(self):
        assert list(chunk_checklist("Just a plain paragraph.\nAnother line.")) == []

    def test_short_pure_checklist_is_one_chunk(self):
        text = "- One\n- Two\n- Three"
        chunks = list(chunk_checklist(text))
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "checklist"
        assert all(item in chunks[0].content for item in ("One", "Two", "Three"))


class TestChecklistContextPrefix:
    """Regression coverage: checklist items used to lose all lexical
    connection to their own topic once split out from the preamble that
    introduced them ("Eligibility for a VA loan depends on...following
    categories:" / "- Veterans who served..."), so a query using the
    preamble's own words (VA, eligible, loan) never matched the bullets
    that were the actual answer. Each item now carries its preamble as
    verbatim prefix -- still no synthesis, just not discarding context
    that already existed in the source."""

    VA_LIST = (
        "Eligibility for a VA loan depends on service history, and "
        "applicants fall into one of the following categories:\n"
        "- Veterans who served the minimum active-duty service "
        "requirement during wartime or peacetime\n"
        "- Current serving members with at least ninety continuous days "
        "of active duty under their belt"
    )

    def test_long_items_are_prefixed_with_their_preamble(self):
        """Unchanged in substance: a split-out bullet must keep the words
        its own topic is named by. Short lists are no longer split at all
        (see TestShortListsStayWhole), so the case is stated with the
        substantial items this rule was written for."""
        items = [c for c in chunk_checklist(self.VA_LIST)
                 if c.chunk_type == "checklist"]
        assert len(items) == 2
        assert all("VA loan" in c.content for c in items)

    def test_preamble_chunk_itself_is_not_double_prefixed(self):
        preamble = [c for c in chunk_checklist(self.VA_LIST)
                    if c.chunk_type == "paragraph"]
        assert preamble
        assert preamble[0].content.endswith("categories:")

    def test_short_list_without_a_preamble_is_one_chunk(self):
        chunks = list(chunk_checklist("- One\n- Two"))
        assert len(chunks) == 1
        assert "One" in chunks[0].content and "Two" in chunks[0].content


class TestMinTokensMerge:
    def _chunker(self, min_tokens=50, max_tokens=300):
        return StructuralChunker(max_tokens=max_tokens, min_tokens=min_tokens)

    def _extracted(self, text: str) -> ExtractedText:
        return ExtractedText(text=text, pages=[text], source_format="txt")

    def test_trailing_small_chunk_merges_into_previous(self):
        long_para = " ".join(["word"] * 60)  # well above min_tokens
        short_trailer = "Short."  # well below min_tokens
        text = f"{long_para}\n\n{short_trailer}"
        chunks = list(self._chunker().chunk(self._extracted(text)))
        assert len(chunks) == 1
        assert chunks[0].content.endswith(short_trailer)

    def test_leading_small_chunk_merges_forward(self):
        short_leader = "Note:"
        long_para = " ".join(["word"] * 60)
        text = f"{short_leader}\n\n{long_para}"
        chunks = list(self._chunker().chunk(self._extracted(text)))
        assert len(chunks) == 1
        assert chunks[0].content.startswith(short_leader)

    def test_small_chunk_does_not_merge_across_sections(self):
        # Two distinct sections' bodies chunked separately still each
        # respect the min_tokens floor independently — but a small chunk
        # must never merge into a different section's chunk.
        chunker = self._chunker()
        small_a = Chunk(content="Short A.", section="Section A", chunk_type="paragraph", page_number=1)
        big_b = Chunk(content=" ".join(["word"] * 60), section="Section B", chunk_type="paragraph", page_number=1)
        merged = chunker._merge_small_chunks([small_a, big_b])
        assert len(merged) == 2
        assert merged[0].section == "Section A"
        assert merged[1].section == "Section B"

    def test_table_and_checklist_chunks_never_merged(self):
        chunker = self._chunker()
        table = Chunk(content="a|b\n1|2", section=None, chunk_type="table", page_number=None)
        small_para = Chunk(content="Short.", section=None, chunk_type="paragraph", page_number=None)
        merged = chunker._merge_small_chunks([table, small_para])
        # Nothing eligible to merge into (predecessor is a table) or from
        # (this is the only paragraph) — both chunks pass through as-is.
        assert len(merged) == 2
        assert merged[0].chunk_type == "table"
        assert merged[1].chunk_type == "paragraph"

    def test_chunk_at_or_above_min_tokens_is_not_merged(self):
        at_threshold = " ".join(["word"] * 50)  # >= min_tokens=50 after *1.3 factor
        text = f"{at_threshold}\n\n{at_threshold}"
        chunks = list(self._chunker(min_tokens=10).chunk(self._extracted(text)))
        assert len(chunks) == 2

    def test_merge_never_undoes_a_max_tokens_split(self):
        """Regression: when min_tokens is close to max_tokens, every chunk
        recursive_chunker just split out of an oversized block is itself
        "small" relative to min_tokens -- without a max_tokens cap on the
        merge, they'd all get folded straight back into one oversized
        chunk, silently undoing the split that was just enforced."""
        text = "This is a test. " * 100  # ~400 tokens, well over max_tokens
        chunks = list(self._chunker(min_tokens=50, max_tokens=50).chunk(self._extracted(text)))
        assert len(chunks) > 1
        for c in chunks:
            assert self._chunker()._count_tokens(c.content) <= 50 + 5  # small slack for join boundaries


class TestDefinitionEntries:
    """Regression coverage for the retrieval failure found by auditing a
    real glossary upload: the chunker correctly emitted one chunk per
    glossary definition (18 chunks), and then _merge_small_chunks glued
    seven of them into a single 1341-char blob (4 chunks total), because
    every definition (23-46 tokens) sits under min_tokens=50.

    The consequence was not a ranking bug but a *retrieval unit* bug:
    "What is equity?" could only ever retrieve the blob, whose extracted
    answer phrase was the Amortization definition and whose 600-char
    excerpt window cut the Equity text off entirely -- scoring 0.0
    relevance and routing to no_answer even though the answer was
    indexed. A self-contained "Term: definition" entry is a complete
    retrieval unit, not the stray fragment the merge pass exists to
    clean up."""

    def _chunker(self):
        return StructuralChunker()

    def _extracted(self, text: str) -> ExtractedText:
        return ExtractedText(text=text, pages=[text], source_format="txt")

    GLOSSARY = (
        "General Banking and Mortgage Glossary\n\n"
        "Core Terms\n\n"
        "Amortization: The process of paying off a loan through regular, "
        "scheduled payments that cover both principal and interest.\n\n"
        "Principal: The original sum of money borrowed, or the remaining "
        "balance owed on a loan, not including interest.\n\n"
        "Equity: The difference between a property's current market value "
        "and the outstanding balance owed on any loans.\n\n"
        "Regulatory Terms\n\n"
        "Truth in Lending Act (TILA): A federal law requiring lenders to "
        "disclose key loan terms and costs to borrowers.\n"
    )

    def test_each_definition_is_its_own_chunk(self):
        chunks = list(self._chunker().chunk(self._extracted(self.GLOSSARY)))
        bodies = [c.content for c in chunks]
        assert len(bodies) == 4, bodies
        assert bodies[0].startswith("Amortization:")
        assert bodies[1].startswith("Principal:")
        assert bodies[2].startswith("Equity:")
        assert bodies[3].startswith("Truth in Lending Act (TILA):")

    def test_definitions_are_typed_and_not_merged(self):
        chunks = list(self._chunker().chunk(self._extracted(self.GLOSSARY)))
        assert all(c.chunk_type == "definition" for c in chunks)

    def test_headings_become_section_metadata_not_chunks(self):
        chunks = list(self._chunker().chunk(self._extracted(self.GLOSSARY)))
        sections = [c.section for c in chunks]
        assert sections == ["Core Terms", "Core Terms", "Core Terms",
                            "Regulatory Terms"]

    def test_definition_content_is_verbatim(self):
        """Excerpts are shown to users verbatim, so the chunker must not
        prepend the section/title to the stored content."""
        chunks = list(self._chunker().chunk(self._extracted(self.GLOSSARY)))
        assert chunks[2].content == (
            "Equity: The difference between a property's current market value "
            "and the outstanding balance owed on any loans."
        )

    def test_prose_with_a_mid_sentence_colon_is_not_a_definition(self):
        """The label must look like a term, not the opening clause of a
        sentence -- otherwise ordinary prose gets typed as a definition
        and becomes exempt from the small-chunk merge."""
        text = "The rule is simple: pay the loan on time every month."
        chunks = list(self._chunker().chunk(self._extracted(text)))
        assert [c.chunk_type for c in chunks] == ["paragraph"]

    def test_label_with_no_body_is_not_a_definition(self):
        """A bare 'Required documents:' line introduces a list; it is a
        heading, not a self-contained definition."""
        text = "Required Documents:\n\nSome following paragraph text here."
        chunks = list(self._chunker().chunk(self._extracted(text)))
        assert all(c.chunk_type != "definition" for c in chunks)

    def test_ordinary_small_fragments_still_merge(self):
        """The merge pass must keep doing its original job."""
        long_para = " ".join(["word"] * 60)
        chunks = list(self._chunker().chunk(
            self._extracted(f"{long_para}\n\nshort trailing bit.")
        ))
        assert len(chunks) == 1

    def test_table_keeps_enclosing_section(self):
        text = (
            "Common ARM Structures\n\n"
            "| ARM Type | Fixed Period |\n|---|---|\n| 5/1 ARM | 5 years |\n"
        )
        chunks = list(self._chunker().chunk(self._extracted(text)))
        assert [c.chunk_type for c in chunks] == ["table"]
        assert chunks[0].section == "Common ARM Structures"


class TestListPreambleIsNotAHeading:
    """Regression from ingesting a real 22-page procedure SOP.

    ``_is_heading`` treats any short line ending in ":" as a heading, so
    in the PDF path a list preamble like "The process ensures:" was
    consumed as a *section* before chunk_checklist ever saw the block.
    That chunker can only prefix its items with a preamble it can see, so
    every bullet was emitted bare: 124 chunks averaging 20 characters,
    like "- Fund Switches".

    A chunk that short has almost no lexical signal for BM25 and a
    near-meaningless embedding. The document indexed cleanly and then
    answered almost nothing -- procedure questions scored 12.5%.

    A colon-terminated line immediately followed by a list item is a
    preamble, not a heading.
    """

    def _chunker(self):
        return StructuralChunker()

    def _pdf(self, text: str) -> ExtractedText:
        return ExtractedText(text=text, pages=[text], source_format="pdf")

    SOP = (
        "The process ensures:\n"
        "- Client retention\n"
        "- Regulatory compliance\n"
        "- Accurate CRM record keeping\n"
    )

    def test_preamble_stays_with_its_list(self):
        chunks = list(self._chunker().chunk(self._pdf(self.SOP)))
        assert chunks, "no chunks produced"
        assert all("The process ensures" in c.content for c in chunks
                   if c.chunk_type == "checklist"), [c.content for c in chunks]

    def test_items_are_retrievable_sized(self):
        """The failure was chunks too small to carry any search signal."""
        chunks = list(self._chunker().chunk(self._pdf(self.SOP)))
        checklist = [c for c in chunks if c.chunk_type == "checklist"]
        assert checklist
        assert all(len(c.content) > 30 for c in checklist), [
            c.content for c in checklist
        ]

    def test_preamble_is_not_promoted_to_a_section(self):
        chunks = list(self._chunker().chunk(self._pdf(self.SOP)))
        assert all(c.section != "The process ensures:" for c in chunks)

    def test_a_colon_line_keeps_its_content(self):
        """Superseded an earlier expectation that "Objective:" becomes a
        section. It should not: a trailing colon introduces content, and
        splitting there separates the label from what it labels. See
        TestColonLabelsAreNotSections for the measurement that changed
        this."""
        text = "Objective:\nTo contact clients approaching product expiry.\n"
        chunks = list(self._chunker().chunk(self._pdf(text)))
        assert any(
            "Objective:" in c.content and "approaching product expiry" in c.content
            for c in chunks
        ), [(c.section, c.content) for c in chunks]

    def test_uppercase_headings_still_become_sections(self):
        text = (
            "PHASE 1 - CLIENT RENEWAL\n"
            "Contact clients whose products approach expiry.\n"
        )
        chunks = list(self._chunker().chunk(self._pdf(text)))
        assert any(c.section == "PHASE 1 - CLIENT RENEWAL" for c in chunks)


class TestColonLabelsAreNotSections:
    """A trailing colon introduces content; it does not start a section.

    Measured on the real SOP: "Every:" became a section and "3 weeks" --
    its entire meaning -- became a 7-character chunk on its own. The
    question "how often should PT rates be reviewed?" could not be
    answered by any chunk, because no chunk contained both the label and
    the value. The same shape orphaned "Include:", "Mark task:",
    "Navigate to:" and "Check:" across the document.

    Real section headings in a procedure document look like "PHASE 1 -
    CLIENT RENEWAL" or "Step 1.1 - ...", not "Every:".
    """

    def _chunker(self):
        return StructuralChunker()

    def _pdf(self, text: str) -> ExtractedText:
        return ExtractedText(text=text, pages=[text], source_format="pdf")

    def test_label_and_value_stay_in_one_chunk(self):
        chunks = list(self._chunker().chunk(self._pdf("Every:\n3 weeks\n")))
        joined = " ".join(c.content for c in chunks)
        assert "Every:" in joined and "3 weeks" in joined
        assert any("Every:" in c.content and "3 weeks" in c.content for c in chunks), [
            c.content for c in chunks
        ]

    def test_label_is_not_promoted_to_a_section(self):
        chunks = list(self._chunker().chunk(self._pdf("Every:\n3 weeks\n")))
        assert all(c.section != "Every:" for c in chunks)

    def test_uppercase_headings_are_still_sections(self):
        text = "PHASE 10 - ONGOING RATE MONITORING\nMaintain best client outcome.\n"
        chunks = list(self._chunker().chunk(self._pdf(text)))
        assert any(c.section == "PHASE 10 - ONGOING RATE MONITORING" for c in chunks)

    def test_a_list_preamble_still_reaches_its_items(self):
        text = "The process ensures:\n- Client retention\n- Regulatory compliance\n"
        chunks = list(self._chunker().chunk(self._pdf(text)))
        checklist = [c for c in chunks if c.chunk_type == "checklist"]
        assert checklist
        assert all("The process ensures" in c.content for c in checklist)


class TestShortListsStayWhole:
    """A list of short items is one retrieval unit, not several.

    Splitting per item is right when each bullet is a substantial
    statement (the VA-eligibility case this chunker was built for). It is
    wrong when the items are two or three words: the real SOP produced
    124 checklist chunks averaging 28 characters, like "- Loan amount".

    Chunks that small are actively harmful, not merely useless. BM25
    normalises by document length, so a 13-character chunk matching one
    query word scores extremely high, and its embedding is dominated by
    those two words. Measured: after the SOP was added, those fragments
    outranked the glossary's own definitions and the glossary suite fell
    from 51/52 to 46/52 -- "how can I calculate the value I have in my
    property?" started answering "Enter: - Property address" instead of
    the Equity definition.
    """

    def _chunker(self):
        return StructuralChunker()

    def _pdf(self, text: str) -> ExtractedText:
        return ExtractedText(text=text, pages=[text], source_format="pdf")

    SHORT_LIST = (
        "Enter:\n"
        "- Property address\n"
        "- Valuation\n"
        "- Outstanding balance\n"
    )

    def test_a_short_list_becomes_one_chunk(self):
        chunks = [c for c in self._chunker().chunk(self._pdf(self.SHORT_LIST))
                  if c.chunk_type == "checklist"]
        assert len(chunks) == 1, [c.content for c in chunks]

    def test_the_whole_list_is_retrievable_together(self):
        chunks = [c for c in self._chunker().chunk(self._pdf(self.SHORT_LIST))
                  if c.chunk_type == "checklist"]
        content = chunks[0].content
        for item in ("Property address", "Valuation", "Outstanding balance"):
            assert item in content
        assert "Enter:" in content

    def test_substantial_items_are_still_split(self):
        """The case this chunker exists for must keep working: each bullet
        is a complete statement a query could match on its own."""
        text = (
            "Eligibility depends on service history, and applicants fall "
            "into one of the following categories:\n"
            "- Veterans who served the minimum active-duty service "
            "requirement during wartime or peacetime\n"
            "- Current serving members with at least ninety continuous "
            "days of active duty under their belt\n"
            "- Surviving spouses of service members who died in the line "
            "of duty or from a service-connected disability\n"
        )
        chunks = [c for c in self._chunker().chunk(self._pdf(text))
                  if c.chunk_type == "checklist"]
        assert len(chunks) == 3, [c.content for c in chunks]
