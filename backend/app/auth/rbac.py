"""RBAC: resolve department access scope from the authenticated user.

The user's allowed departments are extracted from the JWT at request time
and passed to metadata_filters.py, which builds the WHERE clause fragment
that restricts search results to documents the user is permitted to see.

This is the PRIMARY enforcement point for RBAC — the WHERE clause in the
SQL query itself. Response validation does a redundant re-check as a
safety net (CLAUDE.md rule #1).
"""

from __future__ import annotations


# Role hierarchy: higher roles inherit lower scopes.
# Each role maps to the set of departments they can access.
# "super_admin" can access all departments.
ROLE_DEPARTMENTS: dict[str, list[str]] = {
    "super_admin": [],  # empty means "all departments"
    "admin": [],
    "loan_officer": ["general"],
    "underwriter": ["general"],
    "compliance": ["general"],
    "client": ["general"],  # scoped to own client_id; department is additional filter
}

# Default department if none specified.
DEFAULT_DEPARTMENT: str = "general"

# Roles that bypass department filtering entirely.
ADMIN_ROLES: set[str] = {"super_admin", "admin"}

# Roles scoped to a single client_id (cannot see other clients' data).
CLIENT_ROLES: set[str] = {"client"}

# Staff role hierarchy, lowest to highest privilege. This is the single
# source of truth for auth/permissions.py::require_role — it must stay in
# sync with ROLE_DEPARTMENTS above. "client" is deliberately excluded: it
# is a separate, non-staff track (see CLIENT_ROLES) that must never be
# comparable to the staff ladder, so it is checked independently by
# require_role rather than being slotted in here.
STAFF_ROLE_HIERARCHY: list[str] = [
    "compliance", "underwriter", "loan_officer", "admin", "super_admin",
]

assert set(STAFF_ROLE_HIERARCHY) | CLIENT_ROLES == set(ROLE_DEPARTMENTS), (
    "STAFF_ROLE_HIERARCHY + CLIENT_ROLES must cover every role in "
    "ROLE_DEPARTMENTS — a role missing from both would silently bypass "
    "require_role() (see auth/permissions.py)."
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


def get_search_filter(user: dict | None) -> tuple[str, list[str]]:
    """Build the RBAC WHERE clause fragment and parameters for search.

    Returns (clause, params). The clause is appended to the SQL query's
    WHERE clause. If the user is admin, returns ("", []) — no filtering.
    If the user is a client, filters by d.client_id and department.
    """
    if is_admin(user):
        return "", []

    clauses: list[str] = []
    params: list[str] = []

    # Client scope: clients only see documents tagged with their client_id.
    # Authz applied BEFORE retrieval (CLAUDE.md rule #1).
    client_id = resolve_user_client_id(user)
    if client_id is not None:
        clauses.append("d.client_id = %s")
        params.append(client_id)
    elif is_client(user):
        # Client role but no client_id assigned → deny all.
        return "1=0", []

    departments = resolve_user_departments(user)
    if not departments:
        return "1=0", []  # deny all if no departments resolved

    placeholders = ",".join(["%s"] * len(departments))
    clauses.append(f"d.department = ANY(ARRAY[{placeholders}]::text[])")
    params.extend(departments)

    # Phase 3b: staff assigned_clients — expand access to specific clients' docs
    assigned_clients = resolve_user_assigned_clients(user)
    if assigned_clients:
        ph = ",".join(["%s"] * len(assigned_clients))
        clauses.append(
            f"(d.client_id IS NULL OR d.client_id = ANY(ARRAY[{ph}]::text[]))"
        )
        params.extend(assigned_clients)

    # Phase 3b: staff assigned_cases — expand access to specific case docs
    assigned_cases = resolve_user_assigned_cases(user)
    if assigned_cases:
        ph = ",".join(["%s"] * len(assigned_cases))
        clauses.append(
            f"(d.case_id IS NULL OR d.case_id = ANY(ARRAY[{ph}]::text[]))"
        )
        params.extend(assigned_cases)

    clause = " AND ".join(clauses)
    return clause, params
