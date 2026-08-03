"""Document upload API endpoint.

Per CLAUDE.md rule 5: validates and writes to storage/pending/ only.
Does NOT call ingestion logic. Ingestion runs separately via
infra/scripts/run_ingestion.sh → app.documents.ingest_batch
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.auth.permissions import require_role
from app.config import settings
from app.db.postgres.session import acquire
from app.dependencies import require_auth
from app.documents.validation import validate_upload

router = APIRouter()


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)) -> dict:
    """Receive a document upload, validate, write to storage/pending/.

    Returns immediately — ingestion happens in a separate batch process.
    """
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

    unique_name = f"{uuid.uuid4().hex}_{file.filename}"
    dest = pending_dir / unique_name
    dest.write_bytes(content)

    return {
        "message": "File uploaded successfully",
        "filename": file.filename,
        "stored_as": str(dest),
        "size_bytes": file_size,
    }


@router.get("/")
async def list_documents(
    user: dict = Depends(require_auth),
    limit: int = 100,
) -> dict:
    """List documents (requires admin role)."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, source_path, doc_type, department, "
                "is_active, is_approved, version, created_at "
                "FROM documents ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            documents = [dict(row) for row in cur.fetchall()]

    return {"documents": documents}
