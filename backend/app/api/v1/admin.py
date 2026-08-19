"""Admin endpoints for user management and admin analytics."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.hash import bcrypt
from pydantic import BaseModel

from app.auth import rbac
from app.auth.permissions import require_role
from app.db.postgres.session import acquire
from app.dependencies import require_auth
from app.documents import categories

router = APIRouter()


def _validate_departments(
    department: str | None,
    allowed_departments: list[str] | None,
) -> None:
    """Reject department values outside the shared vocabulary.

    RBAC compares these strings against ``documents.department`` in SQL,
    so an unrecognised or mis-cased value does not error -- it silently
    matches nothing, and the user quietly loses access to documents they
    should be able to read. Write time is the only place this is visible.
    """
    candidates = ([department] if department else []) + list(allowed_departments or [])
    unknown = [v for v in candidates if not categories.is_valid_department(v)]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown department(s): {', '.join(unknown)}",
        )


class UserCreate(BaseModel):
    """Fields required to provision a new user account by an admin."""

    email: str
    password: str
    full_name: str | None = None
    role: str = "processor"
    department: str = "general"
    allowed_departments: list[str] = []
    client_id: str | None = None
    assigned_clients: list[str] = []
    assigned_cases: list[str] = []


class UserUpdate(BaseModel):
    """Partial user fields an admin may update.

    `role` is restricted: only super_admin may change a user's role.
    """

    department: Optional[str] = None
    allowed_departments: Optional[list[str]] = None
    is_active: Optional[bool] = None
    role: Optional[str] = None
    client_id: Optional[str] = None
    assigned_clients: Optional[list[str]] = None
    assigned_cases: Optional[list[str]] = None


@router.get("/roles")
async def list_roles(user: dict = Depends(require_auth)) -> dict:
    """Assignable staff roles, lowest privilege first.

    Served rather than duplicated in the frontend: the role list was
    hardcoded in two components, so renaming a role silently left the UI
    offering one the backend would reject.
    """
    require_role(user, "admin")
    return {"roles": list(rbac.STAFF_ROLE_HIERARCHY)}


@router.get("/users")
async def list_users(user: dict = Depends(require_auth)) -> dict:
    """List users. Requires admin role."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, full_name, role, department, "
                "allowed_departments, client_id, assigned_clients, assigned_cases, "
                "is_active, created_at "
                "FROM users ORDER BY id"
            )
            users = [dict(row) for row in cur.fetchall()]

    return {"users": users}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    user: dict = Depends(require_auth),
) -> dict:
    """Provision a new user account. Requires admin role.

    Assigning an elevated role (anything other than ``processor``) is
    restricted to super_admin; plain admins create users with the default
    role. Passwords are stored as bcrypt hashes.
    """
    require_role(user, "admin")

    _validate_departments(body.department, body.allowed_departments)

    if body.role != "processor" and user.get("role") != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super_admin may assign elevated roles",
        )

    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid email address is required",
        )
    if len(body.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters",
        )

    password_hash = bcrypt.hash(body.password)

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cur.fetchone() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A user with that email already exists",
                )

            cur.execute(
                "INSERT INTO users (email, password_hash, full_name, role, "
                "department, allowed_departments, client_id, assigned_clients, "
                "assigned_cases) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id, email, full_name, role, department, "
                "allowed_departments, client_id, assigned_clients, assigned_cases, "
                "is_active, created_at",
                (
                    email,
                    password_hash,
                    body.full_name,
                    body.role,
                    body.department,
                    body.allowed_departments,
                    body.client_id,
                    body.assigned_clients,
                    body.assigned_cases,
                ),
            )
            row = cur.fetchone()
        conn.commit()

    return {"user": dict(row)}


@router.get("/stats")
async def admin_stats(
    user: dict = Depends(require_auth),
    recent: int = 10,
) -> dict:
    """Aggregate KPIs and recent activity for the admin dashboard."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE is_active) AS active "
                "FROM users"
            )
            users = dict(cur.fetchone())

            cur.execute(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE is_active) AS active "
                "FROM documents"
            )
            documents = dict(cur.fetchone())

            cur.execute("SELECT COUNT(*) AS total FROM document_chunks")
            chunks = dict(cur.fetchone())["total"]

            cur.execute(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE outcome = 'no_answer') AS no_answer, "
                "COALESCE(AVG(confidence), 0) AS avg_confidence "
                "FROM audit_log"
            )
            audit = dict(cur.fetchone())

            cur.execute(
                "SELECT COUNT(*) FILTER (WHERE rating = 1) AS thumbs_up, "
                "COUNT(*) FILTER (WHERE rating = -1) AS thumbs_down "
                "FROM feedback"
            )
            feedback = dict(cur.fetchone())

            cur.execute("SELECT COUNT(*) AS total FROM knowledge_gaps")
            gaps = dict(cur.fetchone())["total"]

            cur.execute(
                "SELECT a.id, u.email, a.query, a.confidence, a.outcome, a.created_at "
                "FROM audit_log a LEFT JOIN users u ON u.id = a.user_id "
                "ORDER BY a.created_at DESC LIMIT %s",
                (recent,),
            )
            recent_activity = [dict(row) for row in cur.fetchall()]

    return {
        "stats": {
            "users": users["total"],
            "active_users": users["active"],
            "documents": documents["total"],
            "active_documents": documents["active"],
            "chunks": chunks,
            "queries": audit["total"],
            "no_answer": audit["no_answer"],
            "avg_confidence": round(float(audit["avg_confidence"]), 1),
            "thumbs_up": feedback["thumbs_up"],
            "thumbs_down": feedback["thumbs_down"],
            "knowledge_gaps": gaps,
            "recent_activity": recent_activity,
        }
    }


@router.get("/audit")
async def list_audit(
    user: dict = Depends(require_auth),
    offset: int = 0,
    limit: int = 50,
) -> dict:
    """Paginated query audit log. Requires admin role."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT a.id, u.email, a.query, a.sub_queries, a.confidence, "
                "a.outcome, a.latency_ms, a.created_at "
                "FROM audit_log a LEFT JOIN users u ON u.id = a.user_id "
                "ORDER BY a.created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            audit = [dict(row) for row in cur.fetchall()]

    return {"audit": audit}


@router.get("/feedback")
async def list_feedback(
    user: dict = Depends(require_auth),
    offset: int = 0,
    limit: int = 50,
) -> dict:
    """Feedback review with user email. Requires admin role."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT f.id, u.email, f.rating, f.comment, f.response_id, f.created_at "
                "FROM feedback f LEFT JOIN users u ON u.id = f.user_id "
                "ORDER BY f.created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            feedback = [dict(row) for row in cur.fetchall()]

    return {"feedback": feedback}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UserUpdate,
    user: dict = Depends(require_auth),
) -> dict:
    """Update a user. Requires admin role.

    Role changes are restricted to super_admin; plain admins may only
    update department, allowed_departments, and is_active.
    """
    require_role(user, "admin")

    if body.role is not None and user.get("role") != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super_admin may change a user's role",
        )

    fields: dict[str, object] = {}
    if "department" in body.model_fields_set:
        fields["department"] = body.department
    if "allowed_departments" in body.model_fields_set:
        fields["allowed_departments"] = body.allowed_departments
    if "is_active" in body.model_fields_set:
        fields["is_active"] = body.is_active
    if "client_id" in body.model_fields_set:
        fields["client_id"] = body.client_id
    if "assigned_clients" in body.model_fields_set:
        fields["assigned_clients"] = body.assigned_clients
    if "assigned_cases" in body.model_fields_set:
        fields["assigned_cases"] = body.assigned_cases
    if "role" in body.model_fields_set:
        fields["role"] = body.role

    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No updatable fields provided",
        )

    _validate_departments(
        fields.get("department"), fields.get("allowed_departments"),
    )

    set_clause = ", ".join(f"{c} = %s" for c in fields)
    params = list(fields.values())

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE users SET {set_clause} WHERE id = %s "
                 "RETURNING id, email, full_name, role, department, "
                 "allowed_departments, client_id, assigned_clients, assigned_cases, "
                 "is_active, created_at",
                (*params, user_id),
            )
            row = cur.fetchone()
        conn.commit()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return {"user": dict(row)}
