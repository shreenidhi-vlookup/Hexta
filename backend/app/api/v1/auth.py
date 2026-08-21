"""Auth endpoints (JWT login, verification).

Password storage: bcrypt via passlib. This is the production-grade
password hashing scheme — resistant to brute-force and GPU-accelerated
cracking attacks.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.hash import bcrypt
from pydantic import BaseModel

from app.auth.jwt_handler import create_token, verify_token
from app.auth.rate_limit import limiter
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
async def login(request: Request, body: LoginRequest) -> LoginResponse:
    """Authenticate with email + password, return a JWT.

    Protected by a per-IP request budget and a brute-force lockout that
    blocks an email/IP after repeated failed attempts (returns 429).
    """
    ip = request.client.host if request.client else "unknown"

    if limiter.is_locked(ip, body.email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Try again later.",
        )
    if not limiter.check_request(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login requests. Please wait a moment and retry.",
        )

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash, role, department, "
                "allowed_departments, client_id, assigned_clients, assigned_cases "
                "FROM users "
                "WHERE email = %s AND is_active = true",
                (body.email,),
            )
            row = cur.fetchone()

    if row is None or not bcrypt.verify(body.password, row["password_hash"]):
        limiter.register_failure(ip, body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    limiter.clear(ip, body.email)

    token = create_token(
        subject=str(row["id"]),
        role=row["role"],
        department=row["department"],
        allowed_departments=list(row["allowed_departments"] or []),
        client_id=row["client_id"],
        assigned_clients=list(row["assigned_clients"] or []),
        assigned_cases=list(row["assigned_cases"] or []),
        email=row["email"],
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
