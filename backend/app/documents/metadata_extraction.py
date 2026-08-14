"""Metadata extraction from document content.

Extracts document-level metadata such as title, document type, and
department from file name, content headers, and structural patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.documents import categories
from app.documents.text_extraction import ExtractedText


@dataclass
class DocumentMetadata:
    title: str
    doc_type: str = "policy"
    department: str = "general"
    source_path: str | None = None
    client_id: str | None = None
    property_id: str | None = None
    case_id: str | None = None


_TITLE_PATTERNS = [
    re.compile(r"^(.*?)\s*—\s*", re.MULTILINE),
    re.compile(r"^#\s+(.+)$", re.MULTILINE),
]

_DOC_TYPE_KEYWORDS = {
    "underwriting": "underwriting",
    "eligibility": "eligibility",
    "compliance": "compliance",
    "policy": "policy",
    "procedure": "procedure",
    "guideline": "policy",
    "requirement": "policy",
}


def extract_metadata(
    extracted: ExtractedText,
    file_path: str | Path,
    doc_type: str | None = None,
    department: str | None = None,
) -> DocumentMetadata:
    """Infer metadata from file path and initial content lines.

    ``doc_type`` and ``department`` are the admin's explicit choice from
    the upload form and take precedence over inference — detection reads
    keywords out of the first 2000 characters, so it misfiles anything
    that merely mentions a category.

    An unrecognised value falls back rather than raising: the upload
    endpoint already rejects those, so anything invalid arriving here came
    from a hand-edited sidecar and must not be able to fail a batch run.

    ``department`` is never inferred — there is nothing in a document's
    text that reliably says who should be allowed to read it — so it falls
    back to the default rather than to a guess.
    """
    path = Path(file_path)
    title = _guess_title(extracted, path)
    source_path = str(path)

    if (
        doc_type
        and doc_type != categories.AUTO_DOC_TYPE
        and categories.is_valid_doc_type(doc_type)
    ):
        resolved_type = doc_type
    else:
        resolved_type = _guess_doc_type(extracted)

    if department and categories.is_valid_department(department):
        resolved_department = department
    else:
        resolved_department = categories.DEFAULT_DEPARTMENT

    return DocumentMetadata(
        title=title,
        doc_type=resolved_type,
        department=resolved_department,
        source_path=source_path,
    )


def _guess_title(extracted: ExtractedText, path: Path) -> str:
    lines = [l.strip() for l in extracted.text.split("\n") if l.strip()][:5]
    for line in lines:
        if len(line.split()) <= 12 and not line.islower():
            return line
    if lines:
        return lines[0][:80]
    return path.stem


def _guess_doc_type(extracted: ExtractedText) -> str:
    first_lines = extracted.text.lower()[:2000]
    for keyword, doc_type in _DOC_TYPE_KEYWORDS.items():
        if keyword in first_lines:
            return doc_type
    return "policy"
