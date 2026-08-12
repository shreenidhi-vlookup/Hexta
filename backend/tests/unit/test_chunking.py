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
    def test_preamble_before_first_bullet_is_paragraph_not_checklist(self):
        text = "Required documents for your application:\n- Pay stubs\n- Bank statements"
        chunks = list(chunk_checklist(text))
        assert chunks[0].chunk_type == "paragraph"
        assert chunks[0].content == "Required documents for your application:"
        assert chunks[1].chunk_type == "checklist"
        assert chunks[1].content == "- Pay stubs"
        assert chunks[2].chunk_type == "checklist"
        assert chunks[2].content == "- Bank statements"

    def test_no_list_items_yields_nothing(self):
        assert list(chunk_checklist("Just a plain paragraph.\nAnother line.")) == []

    def test_pure_checklist_all_items_typed_checklist(self):
        text = "- One\n- Two\n- Three"
        chunks = list(chunk_checklist(text))
        assert len(chunks) == 3
        assert all(c.chunk_type == "checklist" for c in chunks)


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
