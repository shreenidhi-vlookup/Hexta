"""Document management API endpoints.

Per CLAUDE.md rule 5: the upload endpoint lives in upload.py.
This file only contains the list endpoint for admin review.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.permissions import require_role
from app.dependencies import require_auth
from app.db.postgres.session import acquire

router = APIRouter()


@router.get("/")
async def list_documents(
    user: dict = Depends(require_auth),
    offset: int = 0,
    limit: int = 100,
) -> dict:
    """List documents (requires admin role)."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, source_path, doc_type, department, "
                "is_active, is_approved, version, created_at "
                "FROM documents ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            documents = [dict(row) for row in cur.fetchall()]

    return {"documents": documents}
