"""RBAC: resolve department access scope from the authenticated user.

The user's allowed departments are extracted from the JWT at request time
and passed to metadata_filters.py, which builds the WHERE clause fragment
that restricts search results to documents the user is permitted to see.

This is the PRIMARY enforcement point for RBAC — the WHERE clause in the
SQL query itself. Response validation does a redundant re-check as a
safety net (CLAUDE.md rule #1).
"""

from __future__ import annotations


# Default department if none specified.
DEFAULT_DEPARTMENT: str = "general"

# Roles that bypass RBAC filtering entirely.
ADMIN_ROLES: set[str] = {"super_admin", "admin"}

# Roles scoped to a single client_id (cannot see other clients' data).
CLIENT_ROLES: set[str] = {"client"}

# Staff role hierarchy, lowest to highest privilege. Single source of truth
# for auth/permissions.py::require_role.
#
# Two working tiers by design: a *processor* (adviser, case handler) does
# the day-to-day work and may upload; an *admin* manages the knowledge base
# and is the only one who can approve an upload into it. The earlier
# loan_officer / underwriter / compliance split never diverged in behaviour
# — all three resolved to the same access — so it added ceremony without
# adding a boundary, and made "who can do what" harder to answer than it
# needed to be.
#
# "client" is deliberately excluded: it is a separate, non-staff track (see
# CLIENT_ROLES) that must never be comparable to the staff ladder, so
# require_role checks it independently rather than ranking it here.
STAFF_ROLE_HIERARCHY: list[str] = ["processor", "admin", "super_admin"]

assert not (set(STAFF_ROLE_HIERARCHY) & CLIENT_ROLES), (
    "The staff ladder and the client track must stay disjoint — a role in "
    "both would be both ranked and denied by require_role(), and which one "
    "wins would be an accident of check ordering."
)

assert ADMIN_ROLES <= set(STAFF_ROLE_HIERARCHY), (
    "Every ADMIN_ROLE must appear in STAFF_ROLE_HIERARCHY: ADMIN_ROLES "
    "bypasses the search filter, so a role missing from the ladder would "
    "read everything while failing every require_role() check."
)


def is_client(user: dict | None) -> bool:
    """Check if the user is a client (scoped to their own client_id only)."""
    if user is None:
        return False
    return user.get("role") in CLIENT_ROLES


def resolve_user_departments(user: dict | None) -> list[str]:
    """Extract the full list of departments a user may access.

    A user can access:
    1. Their own department
    2. Any departments in their allowed_departments claim (from JWT)
    """
    if user is None:
        return []

    departments = {user.get("department", DEFAULT_DEPARTMENT)}
    departments.update(user.get("allowed_departments") or [])

    return sorted(departments)


def resolve_user_client_id(user: dict | None) -> str | None:
    """Extract the client_id scope for a client user.

    Returns the client_id if the user is a client with one assigned,
    or None for staff/admin users (no client scope).
    """
    if user is None:
        return None
    if user.get("role") in CLIENT_ROLES:
        return user.get("client_id")
    return None


def resolve_user_assigned_clients(user: dict | None) -> list[str]:
    """Extract assigned_clients scope for staff users (Phase 3b).

    Staff users with assigned_clients can see documents for those
    client_ids (in addition to department-scoped internal docs).
    Returns empty list if the user has no assigned clients.
    """
    if user is None:
        return []
    if is_client(user):
        return []
    assigned = user.get("assigned_clients") or []
    return list(assigned)


def resolve_user_assigned_cases(user: dict | None) -> list[str]:
    """Extract assigned_cases scope for staff users (Phase 3b).

    Staff users with assigned_cases can see documents tagged with those
    case_ids.
    """
    if user is None:
        return []
    if is_client(user):
        return []
    assigned = user.get("assigned_cases") or []
    return list(assigned)


def is_admin(user: dict | None) -> bool:
    """Check if the user has admin-level access (bypasses RBAC)."""
    if user is None:
        return False
    return user.get("role") in ADMIN_ROLES


# NOTE: get_search_filter used to live here as well, carrying different
# rules from the copy in search/metadata_filters.py, and nothing imported
# it. Two functions that both look authoritative about who may read what
# is how an access bug hides, so the filter now lives in exactly one
# place: search/metadata_filters.py (CLAUDE.md rule #1).
#
# resolve_user_assigned_clients / resolve_user_assigned_cases above are
# kept deliberately: they are the scoping primitives client records will
# need, and they have no behaviour of their own to drift.
