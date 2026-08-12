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
    """
    lines = text.split("\n")
    if not any(_is_list_item(l.strip()) for l in lines):
        return

    current_item: list[str] = []
    current_is_list = False

    def _flush() -> Iterator[ChecklistChunk]:
        if current_item:
            yield ChecklistChunk(
                content="\n".join(current_item),
                section=section,
                chunk_type="checklist" if current_is_list else "paragraph",
                page_number=page_number,
            )

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