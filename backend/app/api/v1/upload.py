"""Document upload API endpoint.

Per CLAUDE.md rule 5, this endpoint only validates and writes to
storage/pending/. It does NOT run ingestion in-process. Instead, after
the file is persisted it spawns the ingestion batch as a detached
subprocess (auto_ingest.trigger_ingestion) so the document becomes
searchable automatically without blocking the request handler.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.auth.permissions import require_role
from app.config import settings
from app.dependencies import require_auth
from app.documents import categories, upload_metadata
from app.documents.auto_ingest import trigger_ingestion
from app.documents.validation import validate_upload

router = APIRouter()


def _resolve_category(
    doc_type: str | None,
    department: str | None,
) -> tuple[str | None, str | None]:
    """Validate the submitted category, normalising "no choice" to None.

    Rejects rather than coerces an unrecognised value: these strings are
    compared against document rows in SQL, so quietly accepting "General"
    or "invoice" would write a value no later lookup ever matches -- and
    for department that means a document readable by nobody but admins.
    """
    doc_type = (doc_type or "").strip() or None
    department = (department or "").strip() or None

    if doc_type == categories.AUTO_DOC_TYPE:
        doc_type = None
    if doc_type is not None and not categories.is_valid_doc_type(doc_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown document type: {doc_type}",
        )
    if department is not None and not categories.is_valid_department(department):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown department: {department}",
        )
    return doc_type, department


# Intelliflo owns the client-reference format; this only guards against
# what would break storage or a later SQL lookup, never reshapes the
# value into something that no longer matches Intelliflo's own record.
_MAX_CLIENT_ID_LENGTH = 100


def _validate_client_id(client_id: str | None) -> str | None:
    """Trim and validate the optional client reference for a document.

    Rejects rather than silently truncates or strips: a document tagged
    with a mangled reference is worse than one that failed to tag at all
    (Task 7's RBAC boundary trusts this value to mean the client it says
    it means), so a bad value surfaces immediately at upload, not later
    as an access-control puzzle.
    """
    client_id = (client_id or "").strip() or None
    if client_id is None:
        return None
    if len(client_id) > _MAX_CLIENT_ID_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Client reference too long (max {_MAX_CLIENT_ID_LENGTH} characters)",
        )
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in client_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client reference contains control characters",
        )
    return client_id


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str | None = Form(None),
    department: str | None = Form(None),
    client_id: str | None = Form(None),
    user: dict = Depends(require_auth),
) -> dict:
    """Receive a document upload, validate, write to storage/pending/.

    ``doc_type`` and ``department`` are the admin's category choice. Both
    are optional: an absent doc_type leaves the type to content detection
    at ingest, and an absent department falls back to the default.

    ``client_id`` is a third, independent optional field: the Intelliflo
    client reference this document belongs to. Absent, it stays NULL and
    the document is firm-wide staff knowledge, unchanged from before this
    field existed. Set, it scopes the document to that client — enforced
    at retrieval time by the RBAC filter (search/metadata_filters.py),
    not here; this endpoint only validates and stores the reference.

    Returns immediately — ingestion happens in a separate batch process.

    Open to processors, not just admins: staff being unable to contribute
    what they know is the bottleneck this is meant to remove. The gate is
    approval, not upload — ingestion writes ``is_approved = false`` and the
    version filter requires true, so nothing an upload adds is retrievable
    (by anyone, including its uploader) until an admin approves it.
    """
    require_role(user, "processor")

    # Before the file is read, so a bad category or client reference
    # costs nothing.
    resolved_type, resolved_department = _resolve_category(doc_type, department)
    resolved_client_id = _validate_client_id(client_id)

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided",
        )

    file_size = 0
    content = b""
    while chunk := await file.read(8192):
        file_size += len(chunk)
        content += chunk

    result = validate_upload(file.filename, file_size)
    if not result.valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error,
        )

    pending_dir = Path(settings.storage_pending_dir)
    pending_dir.mkdir(parents=True, exist_ok=True)

    # Defense in depth: validate_upload already rejects filenames with path
    # components, but strip to the basename here too so this line can never
    # be the one that turns an unsanitized filename into a traversal write.
    unique_name = f"{uuid.uuid4().hex}_{Path(file.filename).name}"
    dest = pending_dir / unique_name
    dest.write_bytes(content)

    # Recorded beside the file so the batch ingester (a separate process)
    # can pick it up; the handler itself still never ingests.
    upload_metadata.write_sidecar(
        dest,
        resolved_type,
        resolved_department,
        uploaded_by=user.get("id"),
        client_id=resolved_client_id,
    )

    indexed = trigger_ingestion(pending_dir)

    return {
        "message": (
            "File uploaded successfully and queued for indexing."
            if indexed
            else "File uploaded successfully. Manual ingestion required."
        ),
        "filename": file.filename,
        "stored_as": str(dest),
        "size_bytes": file_size,
        "indexing": indexed,
        "doc_type": resolved_type,
        "department": resolved_department,
        "client_id": resolved_client_id,
    }