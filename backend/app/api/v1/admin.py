"""Admin endpoints for user management."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.permissions import require_role
from app.dependencies import require_auth
from app.db.postgres.session import acquire

router = APIRouter()


@router.get("/users")
async def list_users(user: dict = Depends(require_auth)) -> dict:
    """List users. Requires admin role."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, full_name, role, department, allowed_departments, "
                "is_active, created_at FROM users ORDER BY id"
            )
            users = [dict(row) for row in cur.fetchall()]

    return {"users": users}
