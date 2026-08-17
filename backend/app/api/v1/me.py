"""Self-service endpoints for the authenticated user's own record.

Stage 2 Task 6: a processor assigns *themselves* to a client and then
retrieves that client's documents (search/metadata_filters.py, Task 7) --
no admin in the loop, so no bottleneck. Every endpoint here operates on
the caller's own row only; it must never accept another user's id, or a
processor could grant themselves access to a colleague's client scope by
naming them instead of themselves. Admin-driven assignment (naming any
user) stays exactly where it already is: admin.py's PATCH
/admin/users/{id}.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.permissions import require_role
from app.db.postgres.session import acquire
from app.dependencies import require_auth

logger = logging.getLogger(__name__)
router = APIRouter()

# Same limits as upload.py::_validate_client_id -- Intelliflo owns the
# reference format, this only guards what would break storage or a SQL
# lookup, never reshapes a valid-but-unusual value.
_MAX_CLIENT_ID_LENGTH = 100


class ClientAssignment(BaseModel):
    client_id: str


def _validate_client_id(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id is required",
        )
    if len(value) > _MAX_CLIENT_ID_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"client_id too long (max {_MAX_CLIENT_ID_LENGTH} characters)",
        )
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id contains control characters",
        )
    return value


@router.get("/clients")
async def list_my_clients(user: dict = Depends(require_auth)) -> dict:
    """The caller's own assigned clients -- never anyone else's.

    require_auth already returns the row's assigned_clients (dependencies.py
    reads it from Postgres per request), so this needs no query of its own.
    """
    require_role(user, "processor")
    return {"assigned_clients": list(user.get("assigned_clients") or [])}


@router.post("/clients")
async def assign_my_client(
    body: ClientAssignment,
    user: dict = Depends(require_auth),
) -> dict:
    """Assign the caller themselves to a client. Idempotent.

    The WHERE clause is always ``id = %s`` with the *authenticated*
    caller's own id -- there is no id in the request body a client could
    substitute to assign someone else.
    """
    require_role(user, "processor")
    client_id = _validate_client_id(body.client_id)

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET assigned_clients = "
                "  (SELECT array_agg(DISTINCT x) FROM unnest("
                "     COALESCE(assigned_clients, '{}') || %s::text[]"
                "  ) AS x) "
                "WHERE id = %s "
                "RETURNING assigned_clients",
                ([client_id], user["id"]),
            )
            row = cur.fetchone()
        conn.commit()

    logger.info("client assignment: user=%s assigned client=%r", user["id"], client_id)
    return {"assigned_clients": list((row["assigned_clients"] if row else None) or [])}


@router.delete("/clients/{client_id}")
async def release_my_client(
    client_id: str,
    user: dict = Depends(require_auth),
) -> dict:
    """Release the caller's own assignment to a client. Idempotent --
    releasing a client the caller was never assigned to is a no-op, not
    an error."""
    require_role(user, "processor")
    client_id = _validate_client_id(client_id)

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET assigned_clients = "
                "  array_remove(COALESCE(assigned_clients, '{}'), %s) "
                "WHERE id = %s "
                "RETURNING assigned_clients",
                (client_id, user["id"]),
            )
            row = cur.fetchone()
        conn.commit()

    logger.info("client assignment released: user=%s client=%r", user["id"], client_id)
    return {"assigned_clients": list((row["assigned_clients"] if row else None) or [])}
