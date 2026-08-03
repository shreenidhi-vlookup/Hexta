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
    role: str = "loan_officer",
    department: str = "general",
    allowed_departments: list[str] | None = None,
) -> str:
    """Create a signed JWT for the given user.

    The token carries RBAC-relevant claims used by metadata_filters.py
    at search time: user role, primary department, and the full list of
    departments the user may query.
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
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> dict | None:
    """Verify a JWT and return its payload, or None if invalid/expired."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception:
        return None


def decode_for_audit(token: str) -> dict | None:
    """Decode a JWT without verification (for audit logging of failed tokens)."""
    try:
        # Decode without verification to extract the subject for auditing
        # even if the token is expired/invalid.
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None
