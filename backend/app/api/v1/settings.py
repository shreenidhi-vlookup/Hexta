"""User settings endpoints.

Provides read/write access to per-user UI preferences.
Currently supports the ``show_related_questions`` toggle.
"""

from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db.postgres.session import acquire
from app.dependencies import require_auth

router = APIRouter()


class UserSettingsRequest(BaseModel):
    show_related_questions: bool


class UserSettingsResponse(BaseModel):
    show_related_questions: bool


@router.get("/", response_model=UserSettingsResponse)
async def get_user_settings(
    user: Annotated[dict, Depends(require_auth)],
) -> UserSettingsResponse:
    """Read the current user's settings."""
    with acquire() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                "SELECT show_related_questions FROM user_settings WHERE user_id = %s",
                (user["id"],),
            )
            row = cur.fetchone()

    if row is None:
        return UserSettingsResponse(show_related_questions=True)

    return UserSettingsResponse(show_related_questions=row["show_related_questions"])


@router.put("/", response_model=UserSettingsResponse)
async def update_user_settings(
    payload: UserSettingsRequest,
    user: Annotated[dict, Depends(require_auth)],
) -> UserSettingsResponse:
    """Update the current user's settings."""
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_settings (user_id, show_related_questions, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (user_id)
                DO UPDATE SET show_related_questions = EXCLUDED.show_related_questions,
                              updated_at = now()
                """,
                (user["id"], payload.show_related_questions),
            )
        conn.commit()

    return UserSettingsResponse(show_related_questions=payload.show_related_questions)