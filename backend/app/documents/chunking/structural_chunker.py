"""Structural chunker for document ingestion.

Splits document text into chunks that respect document structure:
- Tables are kept as single chunks (never split mid-table)
- Headings create chunk boundaries
- Paragraphs are grouped into chunks of ~200–500 tokens
- Checklists (bullet/numbered lists) are split into individual items

Uses table_chunker and checklist_chunker for specialized detection
(Final_System_Design.md §6, Final_Tech_Stack.md: "Hybrid Structural Chunking").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from app.documents.chunking.checklist_chunker import chunk_checklist
from app.documents.chunking.recursive_chunker import recursive_chunk
from app.documents.chunking.table_chunker import chunk_table
from app.documents.text_extraction import ExtractedText


@dataclass
class Chunk:
    content: str
    section: str | None
    chunk_type: str
    page_number: int | None
    summary: str | None = None


# --- Definition / glossary entry detection --------------------------------
#
# A "Term: definition text" block is a self-contained retrieval unit: it
# names exactly one concept and answers exactly one question. Treating it
# as such is what keeps "What is equity?" from having to retrieve a blob
# that also defines amortization, APR, principal and four other terms.
#
# The label has to look like a *term* rather than the opening clause of a
# sentence, or ordinary prose ("The rule is simple: pay on time") would be
# typed as a definition and become exempt from the small-chunk merge. The
# discriminator is title-casing: every word in the label is capitalised,
# an acronym, a number, or one of the lowercase connectives that appear
# inside real titles ("Truth in Lending Act", "Real Estate Settlement
# Procedures Act"). "The rule is simple" fails on "rule".
_DEFINITION_RE = re.compile(r"^([^\n:]{2,70}):[ \t]+(\S.*)", re.DOTALL)

# Lowercase words allowed inside an otherwise title-cased label.
_TITLE_CONNECTIVES = frozenset(
    ("a", "an", "and", "as", "at", "by", "for", "from", "in", "of",
     "on", "or", "the", "to", "with")
)


def _is_title_like(label: str) -> bool:
    """True when every word in ``label`` is consistent with a title/term."""
    words = [w for w in re.split(r"[\s/]+", label.strip()) if w]
    if not words or len(words) > 8:
        return False
    for i, word in enumerate(words):
        # Strip surrounding punctuation/parentheses: "(APR)" -> "APR".
        bare = word.strip("()[[]{},.;\"'")
        if not bare:
            continue
        if bare[0].isupper() or bare[0].isdigit():
            continue
        # A lowercase connective is fine mid-label, never as the first word.
        if i > 0 and bare.lower() in _TITLE_CONNECTIVES:
            continue
        return False
    return True


def _definition_term(block: str) -> str | None:
    """Return the defined term if ``block`` is a "Term: definition" entry."""
    match = _DEFINITION_RE.match(block.strip())
    if not match:
        return None
    label = match.group(1).strip()
    return label if _is_title_like(label) else None


@dataclass
class StructuralChunker:
    max_tokens: int = 300
    min_tokens: int = 50

    def chunk(self, extracted: ExtractedText) -> Iterator[Chunk]:
        """Chunk the extracted text, respecting structure."""
        if extracted.source_format == "pdf":
            raw = list(self._chunk_pdf(extracted))
        else:
            raw = list(self._chunk_plain(extracted))
        yield from self._merge_small_chunks(raw)

    def _merge_small_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Fold undersized paragraph chunks into a neighbor.

        ``min_tokens`` was declared on this dataclass but never enforced —
        any paragraph chunk under the threshold (a stray one-line "Note:",
        a trailing sentence fragment left over after a max_tokens flush,
        ...) was emitted as its own standalone chunk. A handful of words
        makes a low-signal embedding and a weak BM25 document; it rarely
        contains a complete, retrievable answer on its own. Only
        ``chunk_type == "paragraph"`` chunks in the same section are
        merged — tables/checklists are structurally meaningful as-is and
        are never touched. Merges backward into the previous chunk when
        possible so no content is dropped; a chunk with no eligible
        predecessor (e.g. the very first chunk in a section) merges
        forward into the next one instead.

        A merge only happens if the *result* still fits within
        max_tokens. Without that cap, a document split by
        recursive_chunker into several chunks each just under max_tokens
        (e.g. when min_tokens is close to max_tokens) would get every
        one of those chunks immediately re-merged back into a single
        oversized blob here, silently undoing the split that was just
        enforced.
        """
        if not chunks:
            return chunks

        merged: list[Chunk] = []
        for c in chunks:
            is_small = (
                c.chunk_type == "paragraph"
                and self._count_tokens(c.content) < self.min_tokens
            )
            fits = (
                merged
                and self._count_tokens(merged[-1].content + "\n" + c.content)
                <= self.max_tokens
            )
            if (
                is_small
                and fits
                and merged[-1].chunk_type == "paragraph"
                and merged[-1].section == c.section
            ):
                merged[-1] = Chunk(
                    content=merged[-1].content + "\n" + c.content,
                    section=merged[-1].section,
                    chunk_type="paragraph",
                    page_number=merged[-1].page_number,
                )
            else:
                merged.append(c)

        if (
            len(merged) >= 2
            and merged[0].chunk_type == "paragraph"
            and self._count_tokens(merged[0].content) < self.min_tokens
            and merged[1].chunk_type == "paragraph"
            and merged[1].section == merged[0].section
            and self._count_tokens(merged[0].content + "\n" + merged[1].content)
            <= self.max_tokens
        ):
            merged[1] = Chunk(
                content=merged[0].content + "\n" + merged[1].content,
                section=merged[1].section,
                chunk_type="paragraph",
                page_number=merged[1].page_number,
            )
            merged.pop(0)

        return merged

    def _chunk_pdf(self, extracted: ExtractedText) -> Iterator[Chunk]:
        """Chunk PDF pages, attempting table detection per page."""
        for page_idx, page_text in enumerate(extracted.pages):
            if not page_text.strip():
                continue
            page_num = page_idx + 1
            sections = self._split_sections(page_text)
            for section_title, body in sections:
                yield from self._chunk_section(body, section_title, page_num)

    def _split_sections(self, text: str) -> list[tuple[str | None, str]]:
        """Split text into (section_title, body) pairs based on heading patterns."""
        lines = text.split("\n")
        sections: list[tuple[str | None, str]] = []
        current_title: str | None = None
        current_body: list[str] = []

        for line in lines:
            stripped = line.strip()
            if self._is_heading(stripped):
                if current_body:
                    sections.append(
                        (current_title, "\n".join(current_body).strip())
                    )
                current_title = stripped
                current_body = []
            else:
                current_body.append(line)

        if current_body:
            sections.append(
                (current_title, "\n".join(current_body).strip())
            )

        return [(title, body) for title, body in sections if body.strip()]

    def _is_heading(self, line: str) -> bool:
        """Detect heading lines."""
        if len(line) <= 80 and len(line.split()) <= 12:
            if line.isupper() or line.endswith(":") or line.endswith("—"):
                return True
            if line.startswith("§") or line.startswith("Section"):
                return True
        return False

    def _chunk_section(
        self, body: str, section: str | None, page_num: int | None
    ) -> Iterator[Chunk]:
        """Split a section body into chunks, preserving tables and checklists."""
        paragraphs = body.split("\n")
        current: list[str] = []

        for para in paragraphs:
            if not para.strip():
                if current:
                    yield from self._yield_text_chunk(current, section, page_num)
                    current = []
                continue

            # Check for specialized chunk types
            table_yielded = list(chunk_table(para, section=section, page_number=page_num))
            if table_yielded:
                if current:
                    yield from self._yield_text_chunk(current, section, page_num)
                    current = []
                for tc in table_yielded:
                    yield Chunk(
                        content=tc.content,
                        section=tc.section,
                        chunk_type=tc.chunk_type,
                        page_number=tc.page_number,
                    )
                continue

            checklist_yielded = list(chunk_checklist(para, section=section, page_number=page_num))
            if checklist_yielded:
                if current:
                    yield from self._yield_text_chunk(current, section, page_num)
                    current = []
                for cc in checklist_yielded:
                    yield Chunk(
                        content=cc.content,
                        section=cc.section,
                        chunk_type=cc.chunk_type,
                        page_number=cc.page_number,
                    )
                continue

            # Fallback: use inline table detection for whitespace-separated tables
            if self._is_table_block(para):
                if current:
                    yield from self._yield_text_chunk(current, section, page_num)
                    current = []
                yield Chunk(
                    content=para,
                    section=section,
                    chunk_type="table",
                    page_number=page_num,
                )
                continue

            # A "Term: definition" line is a complete retrieval unit; keep
            # it atomic instead of letting it accumulate into `current`
            # with its neighbours (see _definition_term).
            if _definition_term(para) is not None:
                if current:
                    yield from self._yield_text_chunk(current, section, page_num)
                    current = []
                yield Chunk(
                    content=para,
                    section=section,
                    chunk_type="definition",
                    page_number=page_num,
                )
                continue

            current.append(para)
            if self._count_tokens("\n".join(current)) >= self.max_tokens:
                yield from self._yield_text_chunk(current, section, page_num)
                current = []

        if current:
            yield from self._yield_text_chunk(current, section, page_num)

    def _yield_text_chunk(
        self, lines: list[str], section: str | None, page_num: int | None
    ) -> Iterator[Chunk]:
        """Yield one or more text chunks from accumulated lines."""
        content = "\n".join(lines)
        if self._count_tokens(content) <= self.max_tokens:
            yield Chunk(
                content=content,
                section=section,
                chunk_type="paragraph",
                page_number=page_num,
            )
        else:
            yield from self._chunk_text_block(content, section, page_num)

    def _chunk_plain(self, extracted: ExtractedText) -> Iterator[Chunk]:
        """Chunk plain text content (txt, md, docx, html).

        Splits on blank lines into logical blocks. Within each block,
        detects tables, checklists, definition entries, and splits overly
        long blocks.

        Standalone heading blocks ("Core Terms", "Regulatory Terms") are
        consumed into ``section`` metadata rather than emitted as chunks:
        a two-word heading makes a useless retrieval unit on its own, and
        as a chunk it was previously swept into the following content by
        the small-chunk merge. Content is stored verbatim -- the section
        is never prepended -- because excerpts are shown to users as
        exact source text.
        """
        text = extracted.text.strip()
        if not text:
            return

        blocks = re.split(r"\n\s*\n", text)
        section: str | None = None

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # Check for specialized chunk types
            table_chunks = list(chunk_table(block, section=section, page_number=None))
            if table_chunks:
                for tc in table_chunks:
                    yield Chunk(
                        content=tc.content,
                        section=tc.section,
                        chunk_type=tc.chunk_type,
                        page_number=tc.page_number,
                    )
                continue

            checklist_chunks = list(chunk_checklist(block, section=section, page_number=None))
            if checklist_chunks:
                for cc in checklist_chunks:
                    yield Chunk(
                        content=cc.content,
                        section=cc.section,
                        chunk_type=cc.chunk_type,
                        page_number=cc.page_number,
                    )
                continue

            if self._is_table_block(block):
                yield Chunk(
                    content=block,
                    section=section,
                    chunk_type="table",
                    page_number=None,
                )
                continue

            if _definition_term(block) is not None:
                yield Chunk(
                    content=block,
                    section=section,
                    chunk_type="definition",
                    page_number=None,
                )
                continue

            if self._is_plain_heading(block):
                section = block
                continue

            yield from self._chunk_text_block(block, section=section)

    def _is_plain_heading(self, block: str) -> bool:
        """True for a standalone heading block in plain text.

        Deliberately stricter than ``_is_heading`` (used on PDF lines,
        where a heading is surrounded by body text on the same page):
        here a heading must be the *entire* block -- one short, title-like
        line with no terminal punctuation. That keeps a genuine short
        sentence ("Short.", "Payments are due monthly.") out, so the
        small-chunk merge still sees it.
        """
        if "\n" in block:
            return False
        if len(block) > 80 or len(block.split()) > 10:
            return False
        if block[-1] in ".!?:;,":
            return False
        return _is_title_like(block)

    def _chunk_text_block(
        self,
        block: str,
        section: str | None = None,
        page_num: int | None = None,
    ) -> Iterator[Chunk]:
        """Split a text block into chunks of reasonable size.

        Delegates the oversized case to recursive_chunker.recursive_chunk(),
        which splits on sentence boundaries first and falls back to clause
        boundaries (commas/semicolons) for any single sentence that alone
        still exceeds max_tokens -- long run-on sentences are common in
        compliance/policy text. This module used to duplicate a weaker,
        sentence-only version of this logic inline with no clause-level
        fallback, while recursive_chunker.py sat unused (see AUDIT.md
        §"Missing Chunker Submodules" / build-plan item 2.4 -- it was
        built per the original design but never wired in).
        """
        if self._count_tokens(block) <= self.max_tokens:
            yield Chunk(
                content=block,
                section=section,
                chunk_type="paragraph",
                page_number=page_num,
            )
            return

        for rc in recursive_chunk(
            block, max_tokens=self.max_tokens, section=section, page_number=page_num
        ):
            yield Chunk(
                content=rc.content,
                section=rc.section,
                chunk_type=rc.chunk_type,
                page_number=rc.page_number,
            )

    def _is_table_block(self, text: str) -> bool:
        """Detect table-like text blocks (2+ rows, consistent columns).

        Tries column-aligned splitting first: cells separated by runs of
        2+ whitespace characters, the convention plain-text tables use to
        align columns. This is the strong signal -- it correctly handles
        multi-word cells ("Property Type", "Investment Property", "Min
        Down Payment"), which the naive any-whitespace split breaks on
        (each row's *word* count stops matching even though its *column*
        count is identical, so a real table silently fails detection and
        gets swallowed into the surrounding paragraph as prose).

        Falls back to splitting on any whitespace for tables that use
        single-space-separated single-word cells with no double-space
        alignment ("col1 col2 col3") -- weaker signal, more prone to
        false-positiving on ordinary prose, but kept so plain tables that
        were already detected before this fix stay detected.
        """
        lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
        if len(lines) < 2:
            return False

        if self._consistent_columns(lines, r"\s{2,}"):
            return True
        return self._consistent_columns(lines, r"\s+")

    @staticmethod
    def _consistent_columns(lines: list[str], cell_sep: str) -> bool:
        cell_counts = [len(re.split(cell_sep, line)) for line in lines]
        if cell_counts[0] < 3:
            return False
        consistent_count = sum(1 for c in cell_counts if c == cell_counts[0])
        return consistent_count >= 2

    def _count_tokens(self, text: str) -> int:
        """Approximate token count (words * 1.3)."""
        return int(len(text.split()) * 1.3)
