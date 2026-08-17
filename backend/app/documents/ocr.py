"""OCR for scanned PDFs using Tesseract.

Optional dependency — only used when pdfplumber cannot extract
text (e.g. scanned image PDFs). Falls back gracefully if
Tesseract is not installed.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from PIL import Image

    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False
    logger.warning("pytesseract/Pillow not installed; OCR disabled")


def extract_text_from_image(image_path: str | Path) -> str:
    """Run OCR on a single image file and return the extracted text."""
    if not HAS_TESSERACT:
        raise RuntimeError("pytesseract and Pillow are required for OCR")
    img = Image.open(str(image_path))
    text = pytesseract.image_to_string(img)
    return text


# Rasterisation resolution. 200 (pdf2image's default) is marginal for
# small or outlined text; 300 is the usual floor for reliable OCR and is
# affordable now that pages are rendered one at a time.
DEFAULT_DPI = 300

# Upper bound on pages OCR'd from a single document. This runs inside the
# detached batch process, where an unbounded loop over a 500-page upload
# would occupy the ingester indefinitely with no visible failure.
DEFAULT_MAX_PAGES = 100


def ocr_pdf_pages(
    pdf_path: str | Path,
    dpi: int = DEFAULT_DPI,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> list[str]:
    """Extract text from each page of a PDF using OCR.

    Returns one string per page. Use this when pdfplumber returns empty or
    low-quality text — a scan, or a PDF whose text was converted to
    outlines on export.

    Pages are rasterised **one at a time**. Converting the whole document
    in a single call materialises every page as a PIL image at once —
    roughly 150-200MB for a 22-page PDF — which survives the development
    container but would very likely exceed the ~200MB production cap
    (CLAUDE.md rule 10). Peak memory here is one page regardless of
    document length.

    A page whose OCR fails yields an empty string rather than aborting:
    one bad page in a long procedure document should cost that page, not
    the whole upload.
    """
    if not HAS_TESSERACT:
        raise RuntimeError("pytesseract and Pillow are required for OCR")

    import pdf2image  # type: ignore

    texts: list[str] = []
    for page_number in range(1, max_pages + 1):
        try:
            images = pdf2image.convert_from_path(
                str(pdf_path),
                dpi=dpi,
                first_page=page_number,
                last_page=page_number,
            )
        except Exception as exc:  # noqa: BLE001 - end of document or bad page
            logger.warning(
                "Rasterising page %d of %s failed: %s",
                page_number, Path(pdf_path).name, exc,
            )
            break
        if not images:
            break  # past the last page

        try:
            texts.append(pytesseract.image_to_string(images[0]))
        except Exception as exc:  # noqa: BLE001 - one page must not fail the doc
            logger.warning(
                "OCR failed on page %d of %s: %s",
                page_number, Path(pdf_path).name, exc,
            )
            texts.append("")

    return texts