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
    """View low-confidence / no-answer queries. Requires admin role.

    Returns gaps with user email (if the gap can be linked to an audit entry),
    acknowledgment status, and the user who acknowledged.
    """
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT kg.id, kg.query, kg.intent, kg.confidence,
                       kg.acknowledged, kg.acknowledged_at,
                       u.email AS acknowledged_by_email
                FROM knowledge_gaps kg
                LEFT JOIN users u ON u.id = kg.acknowledged_by
                ORDER BY kg.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            gaps = [dict(row) for row in cur.fetchall()]

    return {"knowledge_gaps": gaps}


@router.post("/knowledge-gaps/{gap_id}/acknowledge")
async def acknowledge_gap(
    gap_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Mark a knowledge gap as acknowledged (reviewed by an admin)."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE knowledge_gaps SET acknowledged = true, "
                "acknowledged_by = %s, acknowledged_at = now() "
                "WHERE id = %s RETURNING id",
                (user["id"], gap_id),
            )
            row = cur.fetchone()
            conn.commit()

    if row is None:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge gap not found",
        )

    return {"message": "Gap acknowledged", "gap_id": gap_id}
