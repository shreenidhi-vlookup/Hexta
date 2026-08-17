"""Checklist chunker for document ingestion.

Keeps checklist items (bullet points, numbered lists) as
individual chunks so each item is independently searchable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from app.documents.text_extraction import ExtractedText


@dataclass
class ChecklistChunk:
    content: str
    section: str | None
    chunk_type: str = "checklist"
    page_number: int | None = None


def chunk_checklist(text: str, section: str | None = None, page_number: int | None = None) -> Iterator[ChecklistChunk]:
    """Yield individual checklist items from a text block.

    Detects bullet points (-, *, +) and numbered lists (1., 2., etc.)
    and splits them into separate chunks. Only yields chunks if at least
    one list item is detected — plain paragraphs are not treated as
    checklists.

    A block can open with non-list preamble text before the first bullet
    (e.g. "Required documents for your application:\n- Pay stubs\n...").
    That preamble is yielded as its own ``chunk_type="paragraph"`` chunk,
    never as ``"checklist"`` — it isn't a list item and mislabeling it hid
    it from downstream merge/size logic that treats "checklist" chunks as
    already-final.

    Each checklist item's content is prefixed with that preamble (still
    fully verbatim — concatenating two pieces of source text, not
    synthesizing new ones). Without it, splitting "Eligibility for a VA
    loan depends on...following categories:\n- Veterans who served..."
    into separate chunks strips each bullet of every word ("VA",
    "eligible", "loan") a query would actually search on -- a bullet
    like "- Veterans who served the minimum active-duty service
    requirement..." has zero lexical overlap with "who is eligible for
    a VA loan" on its own, so it was consistently outranked by unrelated
    paragraphs that happened to repeat "VA loan" a few times, and never
    made it into the response at all despite being exactly the right
    answer.
    """
    lines = text.split("\n")
    if not any(_is_list_item(l.strip()) for l in lines):
        return

    # A list of short items is one retrieval unit, not several.
    #
    # Splitting per item is right when each bullet is a substantial
    # statement a query could match on its own. It is wrong when the items
    # are two or three words: a real procedure SOP produced 124 checklist
    # chunks averaging 28 characters ("- Loan amount").
    #
    # Fragments that small are actively harmful, not merely useless. BM25
    # normalises by document length, so a 13-character chunk matching one
    # query word scores extremely high, and its embedding is dominated by
    # those two words. Measured: once that SOP joined the corpus, its
    # fragments outranked the glossary's own definitions and the glossary
    # suite fell from 51/52 to 46/52 -- "how can I calculate the value I
    # have in my property?" began answering "Enter: - Property address"
    # instead of the Equity definition.
    if _is_short_list(lines):
        content = "\n".join(l.strip() for l in lines if l.strip())
        yield ChecklistChunk(
            content=content,
            section=section,
            chunk_type="checklist",
            page_number=page_number,
        )
        return

    current_item: list[str] = []
    current_is_list = False
    preamble: str | None = None

    def _flush() -> Iterator[ChecklistChunk]:
        nonlocal preamble
        if not current_item:
            return
        content = "\n".join(current_item)
        if current_is_list and preamble:
            content = f"{preamble} {content}"
        yield ChecklistChunk(
            content=content,
            section=section,
            chunk_type="checklist" if current_is_list else "paragraph",
            page_number=page_number,
        )
        if not current_is_list:
            preamble = content

    for line in lines:
        stripped = line.strip()
        if not stripped:
            yield from _flush()
            current_item = []
            current_is_list = False
            continue

        if _is_list_item(stripped):
            yield from _flush()
            current_item = [stripped]
            current_is_list = True
        else:
            current_item.append(stripped)

    yield from _flush()


# An item shorter than this carries too little text to stand alone as a
# retrieval unit. Comfortably below a real bullet like "Veterans who
# served the minimum active-duty service requirement" (~55 chars) and
# comfortably above a procedure label like "- Loan amount" (13).
_MIN_STANDALONE_ITEM_CHARS = 45

# Above this the list is too large to keep whole -- splitting per item is
# then better than one oversized chunk, whatever the item lengths.
_MAX_WHOLE_LIST_CHARS = 600


def _is_short_list(lines: list[str]) -> bool:
    """True when the list's items are too small to stand alone."""
    items = [l.strip() for l in lines if _is_list_item(l.strip())]
    if not items:
        return False
    total = sum(len(l.strip()) for l in lines if l.strip())
    if total > _MAX_WHOLE_LIST_CHARS:
        return False
    average = sum(len(item) for item in items) / len(items)
    return average < _MIN_STANDALONE_ITEM_CHARS


def _is_list_item(line: str) -> bool:
    """Check if a line is a list item (bullet or numbered)."""
    return bool(
        re.match(r"^[\-\*]\s", line)
        or re.match(r"^\d+[\.\)]\s", line)
    )