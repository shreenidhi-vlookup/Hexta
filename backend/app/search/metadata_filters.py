"""RBAC metadata filters: translate user scope into SQL WHERE clause.

Per CLAUDE.md rule #1: RBAC and active-version filtering happen in the
Postgres WHERE clause at query time — never as a post-hoc check only.

This is the PRIMARY enforcement point.
"""

from __future__ import annotations


def get_search_filter(user: dict | None) -> tuple[str, list]:
    """Build the RBAC WHERE clause fragment and parameters for search.

    Returns (clause, params). The clause is appended to the SQL query's
    WHERE clause. If the user is admin, returns ("", []) — no filtering.
    If the user is a client, filters by d.client_id and department.

    Authz is applied BEFORE retrieval (CLAUDE.md rule #1): the WHERE
    clause restricts rows at the database level, never as a post-hoc check.
    """
    from app.auth.rbac import is_admin, is_client, resolve_user_departments, resolve_user_client_id

    if is_admin(user):
        return "", []

    clauses: list[str] = []
    params: list = []

    # Client scope: clients only see documents tagged with their client_id.
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

    clause = " AND ".join(clauses)
    return clause, params


def get_version_filter(is_approved: bool = True, is_active: bool = True) -> tuple[str, list]:
    """Build the active-version filter clause.

    Only returns approved + active chunks by default.
    """
    conditions: list[str] = []
    params: list = []

    if is_approved:
        conditions.append("c.is_approved = true")
    if is_active:
        conditions.append("c.is_active = true")

    clause = " AND ".join(conditions) if conditions else "(true)"
    return clause, params
