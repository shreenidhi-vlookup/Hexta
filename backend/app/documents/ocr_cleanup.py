"""Repair known OCR artifacts before text reaches the ingestion pipeline.

Applied **only** to OCR output, never to text pdfplumber (or any other
extractor) read directly. This undoes specific, observed Tesseract
failures; running it over already-clean text would be a licence to
corrupt documents that were fine.

Why it exists
-------------
A real 22-page SOP arrived as a PDF whose text had been converted to
outlines on export, so it had to be rasterised and OCR'd. Tesseract read
every bullet "•" as the letter "e", turning each procedure step into
``e Product Transfers (PT)``.

That one character defeats three independent parts of the pipeline, each
of which is correct in isolation:

* ``checklist_chunker`` recognises ``-``, ``*``, ``+`` and numbered
  lists. ``e`` is none of them, so no procedure was chunked as a
  checklist and every step became undifferentiated prose.
* ``api/v1/search.py``'s ``_FRAGMENT_START_RE`` cuts the RRF score of any
  chunk starting with a lowercase letter to 35%, on the reasoning that it
  is a mid-word truncation artifact.
* ``response/package_builder._starts_cleanly`` drops such chunks from the
  answer-phrase candidates entirely.

So the document would have been indexed, scored down, and then made
ineligible to answer anything — quietly, with no error. The fix belongs
here, at the source, rather than in loosening three safeguards that exist
because genuinely broken chunks make bad answers.
"""

from __future__ import annotations

import re

# A bullet Tesseract commonly mis-reads. "o" and "e" are the frequent
# offenders for a filled round bullet; the rest are glyphs it sometimes
# passes through unchanged but which the chunkers do not recognise.
_BULLET_GLYPHS = "e•·o©"

# A bullet line: optional indent, one glyph standing alone, whitespace,
# then actual content. The trailing content requirement is what keeps
# "e.g. ..." and a bare "e" from being rewritten -- the glyph has to be a
# whole token followed by real text.
_BULLET_RE = re.compile(rf"^[ \t]*[{re.escape(_BULLET_GLYPHS)}][ \t]+(?=\S)")

# Arrows in the flowchart page were read as isolated letters. A line of
# one or two of these characters and nothing else carries no content.
_NOISE_CHARS = set("LJ|_—–-")

# A heading captured twice with no separator ("Mortgage Rate
# SecuredMortgage Rate Secured"). Requires a substantial half so short
# numeric strings like "1010" are not mangled into "10".
_MIN_DOUBLED_HALF = 8


def _repair_bullet(line: str) -> str:
    """Turn a mis-read bullet glyph into a marker the chunkers know."""
    if _BULLET_RE.match(line):
        return _BULLET_RE.sub("- ", line, count=1)
    return line


def _is_noise(line: str) -> bool:
    """True for a line that is only mis-read arrow characters."""
    stripped = line.strip()
    if not stripped or len(stripped) > 2:
        return False
    return all(ch in _NOISE_CHARS for ch in stripped)


def _collapse_doubling(line: str) -> str:
    """Collapse a line that is exactly the same text twice."""
    stripped = line.strip()
    half, remainder = divmod(len(stripped), 2)
    if remainder or half < _MIN_DOUBLED_HALF:
        return line
    if stripped[:half] == stripped[half:]:
        return stripped[:half]
    return line


def _is_list_line(line: str) -> bool:
    """True for a repaired list item — bullet or numbered."""
    from app.documents.chunking.checklist_chunker import _is_list_item

    return _is_list_item(line.strip())


def _join_list_blank_lines(lines: list[str]) -> list[str]:
    """Drop blank lines that only separate a list from its own items.

    Rasterised layout has no notion of "same list": the vertical gap
    between bullets comes back as a blank line, which every chunker reads
    as a block boundary. On the real SOP that meant a list's preamble
    reached only its first item and 118 of 124 checklist chunks were
    emitted bare at ~20 characters — far too little text to carry a BM25
    signal or a meaningful embedding.

    A blank line is dropped only when it sits between two list items, or
    between a colon-terminated preamble and the item below it. A blank
    line before ordinary prose is a real paragraph break and survives.
    """
    out: list[str] = []
    for index, line in enumerate(lines):
        if line.strip():
            out.append(line)
            continue

        previous = next(
            (l for l in reversed(out) if l.strip()), ""
        ).strip()
        following = next(
            (l for l in lines[index + 1:] if l.strip()), ""
        ).strip()

        binds_to_list = _is_list_line(following) and (
            _is_list_line(previous) or previous.endswith(":")
        )
        if not binds_to_list:
            out.append(line)
    return out


def clean_ocr_text(text: str) -> str:
    """Repair OCR artifacts in a single page or document of OCR output."""
    if not text:
        return text

    out: list[str] = []
    for line in text.split("\n"):
        if _is_noise(line):
            continue
        out.append(_collapse_doubling(_repair_bullet(line)))
    return "\n".join(_join_list_blank_lines(out))


def clean_ocr_pages(pages: list[str]) -> list[str]:
    """Clean each page, dropping any that hold nothing afterwards.

    A blank page, or one that was only flowchart arrows, produces a chunk
    with no content but a real embedding — which can then be retrieved for
    a vague query and answer nothing.
    """
    cleaned = [clean_ocr_text(page) for page in pages]
    return [page for page in cleaned if page.strip()]
