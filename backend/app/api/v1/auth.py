"""Auth endpoints (JWT login, verification).

Password storage: SHA-256 hash comparison. For production, migrate to
bcrypt/argon2 via passlib — SHA-256 is used here only for initial setup
convenience and must not ship to production without a proper password hasher.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.auth.jwt_handler import create_token, verify_token
from app.config import settings
from app.db.postgres.session import acquire

router = APIRouter()

bearer_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenVerifyResponse(BaseModel):
    valid: bool
    user_id: int | None = None
    email: str | None = None


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    """Authenticate with email + password, return a JWT."""
    password_hash = hashlib.sha256(request.password.encode()).hexdigest()

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash, role, department, "
                "allowed_departments FROM users "
                "WHERE email = %s AND is_active = true",
                (request.email,),
            )
            row = cur.fetchone()

    if row is None or row["password_hash"] != password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_token(
        subject=str(row["id"]),
        role=row["role"],
        department=row["department"],
        allowed_departments=list(row["allowed_departments"] or []),
    )

    return LoginResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_minutes * 60,
    )


@router.post("/verify", response_model=TokenVerifyResponse)
async def verify(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenVerifyResponse:
    """Verify a bearer JWT token's validity."""
    if credentials is None:
        return TokenVerifyResponse(valid=False)

    payload = verify_token(credentials.credentials)
    if payload is None:
        return TokenVerifyResponse(valid=False)

    return TokenVerifyResponse(
        valid=True,
        user_id=int(payload["sub"]) if payload.get("sub") else None,
        email=payload.get("email"),
    )
