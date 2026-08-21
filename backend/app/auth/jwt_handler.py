"""JWT token creation and verification.

Uses HS256 (symmetric) — sufficient for a single-host deployment where
the same backend verifies what the auth endpoint issued. If the API
ever scales to multiple hosts or needs third-party verification, migrate
to RS256 (asymmetric) and add JWKS endpoint support.
"""

from __future__ import annotations

import time

import jwt

from app.config import settings


def create_token(
    subject: str,
    role: str = "processor",
    department: str = "general",
    allowed_departments: list[str] | None = None,
    client_id: str | None = None,
    assigned_clients: list[str] | None = None,
    assigned_cases: list[str] | None = None,
    email: str | None = None,
) -> str:
    """Create a signed JWT for the given user.

    The token carries RBAC-relevant claims used by metadata_filters.py
    at search time: user role, primary department, the full list of
    departments the user may query, and (for client users) the client_id
    scope. Staff may additionally carry assigned_clients and assigned_cases
    for fine-grained scoping (Phase 3b). The email claim lets the
    /verify endpoint return the caller's identity without another DB hit.
    """
    now = int(time.time())
    payload = {
        "sub": subject,
        "role": role,
        "department": department,
        "allowed_departments": allowed_departments or [],
        "iat": now,
        "exp": now + (settings.jwt_expiry_minutes * 60),
    }
    if email is not None:
        payload["email"] = email
    if client_id is not None:
        payload["client_id"] = client_id
    if assigned_clients:
        payload["assigned_clients"] = assigned_clients
    if assigned_cases:
        payload["assigned_cases"] = assigned_cases
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> dict | None:
    """Verify a JWT and return its payload, or None if invalid/expired."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
