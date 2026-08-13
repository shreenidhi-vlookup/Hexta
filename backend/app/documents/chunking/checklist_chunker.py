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


def _is_list_item(line: str) -> bool:
    """Check if a line is a list item (bullet or numbered)."""
    return bool(
        re.match(r"^[\-\*]\s", line)
        or re.match(r"^\d+[\.\)]\s", line)
    )