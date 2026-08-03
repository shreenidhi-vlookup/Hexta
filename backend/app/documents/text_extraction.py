"""Text extraction from common document formats.

Supports PDF (pdfplumber), plain text, DOCX, HTML, and Markdown.
PDF text extraction is always available even without OCR; OCR (Tesseract)
is applied separately in ocr.py for scanned PDFs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import pdfplumber

    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    logger.warning("pdfplumber not installed; PDF support disabled in batch mode")

try:
    import docx

    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False
    logger.warning("python-docx not installed; DOCX support disabled")


@dataclass
class ExtractedText:
    text: str
    pages: list[str]  # one entry per page (empty for plain text formats)
    source_format: str


def extract_text(file_path: str | Path) -> ExtractedText:
    """Extract text from a file, returning text + per-page breakdown."""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".pdf":
        return _extract_pdf(path)
    if ext in (".txt", ".md"):
        return _extract_text_file(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext in (".html", ".htm"):
        return _extract_html(path)

    raise ValueError(f"Unsupported file extension: {ext}")


def _extract_pdf(path: Path) -> ExtractedText:
    if not HAS_PDFPLUMBER:
        raise RuntimeError("pdfplumber is required for PDF extraction")
    pages = []
    full_text = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
            full_text.append(text)
    return ExtractedText(
        text="\n".join(full_text),
        pages=pages,
        source_format="pdf",
    )


def _extract_text_file(path: Path) -> ExtractedText:
    text = path.read_text(encoding="utf-8", errors="replace")
    return ExtractedText(text=text, pages=[text], source_format=path.suffix[1:])


def _extract_docx(path: Path) -> ExtractedText:
    if not HAS_DOCX:
        raise RuntimeError("python-docx is required for DOCX extraction")
    doc = docx.Document(str(path))
    pages = [para.text for para in doc.paragraphs]
    return ExtractedText(
        text="\n".join(p for p in pages if p),
        pages=pages,
        source_format="docx",
    )


def _extract_html(path: Path) -> ExtractedText:
    from html.parser import HTMLParser

    class TextExtractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    content = path.read_text(encoding="utf-8", errors="replace")
    parser = TextExtractor()
    parser.feed(content)
    text = "\n".join(parser.parts)
    return ExtractedText(text=text, pages=[text], source_format="html")
