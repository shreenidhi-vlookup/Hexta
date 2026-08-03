"""Analytics endpoints for admin review."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.permissions import require_role
from app.dependencies import require_auth
from app.db.postgres.session import acquire

router = APIRouter()


@router.get("/knowledge-gaps")
async def knowledge_gaps(
    user: dict = Depends(require_auth),
    limit: int = 50,
) -> dict:
    """View low-confidence / no-answer queries. Requires admin role."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, query, intent, confidence, created_at "
                "FROM knowledge_gaps ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            gaps = [dict(row) for row in cur.fetchall()]

    return {"knowledge_gaps": gaps}
