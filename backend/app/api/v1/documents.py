"""Document management API endpoints.

Per CLAUDE.md rule 5: the upload endpoint lives in upload.py.
This file contains the list endpoint and document approval endpoint for admin review.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.permissions import require_role
from app.db.postgres.session import acquire
from app.dependencies import require_auth
from app.documents import categories

router = APIRouter()


def _categories_payload() -> dict:
    """The category vocabulary, in the shape the upload form needs."""
    return {
        "doc_types": categories.as_options(categories.DOC_TYPES),
        "departments": categories.as_options(categories.DEPARTMENTS),
        "auto_doc_type": categories.AUTO_DOC_TYPE,
        "default_department": categories.DEFAULT_DEPARTMENT,
    }


@router.get("/categories")
async def list_categories(user: dict = Depends(require_auth)) -> dict:
    """Category vocabulary for the upload form.

    Served rather than duplicated in the frontend so that adding a
    category stays a backend-only change.

    Open to processors, not just admins: they upload too, and without this
    the form silently drops both dropdowns and every upload falls back to
    auto-detection. The payload is a static vocabulary — it exposes
    nothing about any document.
    """
    require_role(user, "processor")
    return _categories_payload()


_DOCUMENT_COLUMNS = (
    "id, title, source_path, doc_type, department, "
    "is_active, is_approved, client_id, property_id, case_id, version, "
    "uploaded_by, created_at"
)


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
                f"SELECT {_DOCUMENT_COLUMNS} "
                "FROM documents ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            documents = [dict(row) for row in cur.fetchall()]

    return {"documents": documents}


@router.get("/mine")
async def list_my_documents(
    user: dict = Depends(require_auth),
    offset: int = 0,
    limit: int = 100,
) -> dict:
    """List the caller's own uploads, approved or not.

    A processor may upload but not approve, and an unapproved document is
    invisible everywhere else by design — so without this they would have
    no way to tell a document still awaiting review from one that failed
    to ingest, and would go and ask an admin. That is the exact
    interruption this feature exists to remove.

    Scoped to ``uploaded_by = caller`` rather than role-gated to admin:
    this returns nothing a processor did not themselves submit.
    """
    require_role(user, "processor")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_DOCUMENT_COLUMNS} "
                "FROM documents WHERE uploaded_by = %s "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (user["id"], limit, offset),
            )
            documents = [dict(row) for row in cur.fetchall()]

    return {"documents": documents}


@router.patch("/{document_id}/approve")
async def approve_document(
    document_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Approve a pending document and its chunks (requires admin role)."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET is_approved = true "
                "WHERE id = %s AND is_active = true "
                "RETURNING id, title, is_approved",
                (document_id,),
            )
            doc_row = cur.fetchone()

            if doc_row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found or inactive",
                )

            cur.execute(
                "UPDATE document_chunks SET is_approved = true "
                "WHERE document_id = %s AND is_active = true",
                (document_id,),
            )
            chunks_updated = cur.rowcount

            conn.commit()

    return {
        "message": "Document approved",
        "document_id": doc_row["id"],
        "title": doc_row["title"],
        "chunks_updated": chunks_updated,
    }
