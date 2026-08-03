"""FastAPI dependency injection.

Provides:
- ``get_db`` — yields a pooled Postgres connection per request
- ``get_current_user`` — extracts and verifies JWT, returns the user row
- ``require_department_access`` — RBAC scope resolver from the JWT

Authentication is enforced backend-side. The frontend (static export) has
no server-side auth layer — it stores the JWT client-side and sends it
per-request via the Authorization header.
"""

from __future__ import annotations

from typing import Annotated, Optional

import psycopg
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt_handler import verify_token
from app.config import settings
from app.db.postgres.session import acquire

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> psycopg.Connection:
    """Yield a pooled Postgres connection for a single request."""
    with acquire() as conn:
        yield conn


async def get_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)] = None,
) -> dict | None:
    """Extract and verify JWT from the Authorization header.

    Returns the user dict if valid, None if no token provided
    (callers can decide whether auth is required).
    """
    if credentials is None:
        return None

    token = credentials.credentials
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, full_name, role, department, allowed_departments, is_active "
                "FROM users WHERE id = %s AND is_active = true",
                (user_id,),
            )
            row = cur.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return dict(row)


async def require_auth(
    user: Annotated[dict | None, Depends(get_current_user)] = None,
) -> dict:
    """Dependency that requires a valid authenticated user."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_user_departments(user: dict) -> list[str]:
    """Resolve the full department access scope for a user.

    A user always has access to their own department, plus any
    departments in their allowed_departments list. Used as the RBAC
    pre-filter in the search WHERE clause.
    """
    departments = {user["department"]}
    departments.update(user.get("allowed_departments") or [])
    return list(departments)
