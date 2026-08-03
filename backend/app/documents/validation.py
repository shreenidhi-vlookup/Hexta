"""Validation for uploaded documents.

Checks file extension and size. Per CLAUDE.md rule 5, the API endpoint
only validates — it does not ingest.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import settings

ALLOWED_EXTENSIONS: set[str] = {".pdf", ".txt", ".docx", ".html", ".md"}


@dataclass
class ValidationResult:
    valid: bool
    filename: str
    error: str | None
    file_size: int


def validate_upload(filename: str, file_size: int) -> ValidationResult:
    """Validate a file name and size against configured limits."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return ValidationResult(
            valid=False,
            filename=filename,
            error=f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            file_size=file_size,
        )
    if file_size > settings.max_upload_bytes:
        return ValidationResult(
            valid=False,
            filename=filename,
            error=f"File size {file_size} exceeds limit {settings.max_upload_bytes}",
            file_size=file_size,
        )
    return ValidationResult(
        valid=True,
        filename=filename,
        error=None,
        file_size=file_size,
    )
