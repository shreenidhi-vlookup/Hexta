"""Permission helpers for role-based access control.

Defines the action/resource matrix used by admin endpoints.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.auth.rbac import CLIENT_ROLES, STAFF_ROLE_HIERARCHY as _HIERARCHY

# _HIERARCHY (super_admin > admin > loan_officer > underwriter > compliance)
# lives in rbac.py as the single source of truth, alongside ROLE_DEPARTMENTS
# and CLIENT_ROLES — a module-level assertion there guarantees every role
# is covered by either the hierarchy or CLIENT_ROLES, so this file can't
# silently drift out of sync with the rest of the role taxonomy again.
#
# Any role string not present in _HIERARCHY (a typo, or a future role not
# yet wired in) must be treated the same way as "client": denied, not
# silently let through.


def require_role(user: dict | None, role: str) -> None:
    """Raise 403 if the user's role doesn't meet the minimum requirement.

    Fails closed: a client-scoped role, or any role not present in the
    staff hierarchy, is always denied rather than silently admitted.
    """
    user_role = user.get("role", "loan_officer") if user else "loan_officer"

    if user_role in CLIENT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user_role}' cannot perform this action (requires '{role}')",
        )

    try:
        user_idx = _HIERARCHY.index(user_role)
        required_idx = _HIERARCHY.index(role)
    except ValueError:
        # Unrecognized role on either side — never grant access by default.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user_role}' cannot perform this action (requires '{role}')",
        ) from None

    if user_idx < required_idx:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user_role}' cannot perform this action (requires '{role}')",
        )
