"""RBAC metadata filters: translate user scope into a SQL WHERE clause.

Per CLAUDE.md rule #1, RBAC and active-version filtering happen in the
Postgres WHERE clause at query time — never as a post-hoc check only.

This is the PRIMARY, and now the ONLY, enforcement point. A second
implementation used to live in ``auth/rbac.py`` carrying different rules;
nothing imported it, and the two drifted apart. Two functions that both
look authoritative about who may read what is how an access bug hides, so
there is deliberately just one.

The boundary is **client ownership**, not department:

    admin / super_admin   everything, unfiltered
    processor             every document that belongs to no client
    client                only documents tagged with their own client_id
    anything else         nothing

Department was previously the staff boundary. It no longer is — staff must
be able to answer a mortgage or internal-process question without waiting
on an admin to grant them a department, and in practice every document sat
in "general" so it was never enforcing anything anyway. Department remains
on the document as organisational metadata for filtering and display.

The ``d.client_id IS NULL`` rule is the part to be careful with. No
client-tagged document exists yet, so today it changes nothing — but it
means client records can be introduced later without having to retrofit a
boundary into a system that has already gone fully open.
"""

from __future__ import annotations


def get_search_filter(user: dict | None) -> tuple[str, list]:
    """Build the RBAC WHERE clause fragment and parameters for search.

    Returns ``(clause, params)``. The clause is ANDed into the search
    query's WHERE clause, so authz is applied *before* retrieval rather
    than as a filter over results (CLAUDE.md rule #1).

    Fails closed: an absent user, or any role outside the known staff and
    client tracks, gets ``1=0``. A typo'd role, or a row that escaped the
    role migration, must never be handed the knowledge base by default —
    the same posture ``auth/permissions.require_role`` takes.
    """
    from app.auth.rbac import (
        CLIENT_ROLES,
        STAFF_ROLE_HIERARCHY,
        is_admin,
        is_client,
        resolve_user_client_id,
    )

    if user is None:
        return "1=0", []

    if is_admin(user):
        return "", []

    if is_client(user):
        client_id = resolve_user_client_id(user)
        if not client_id:
            # Client role with no client assigned: scope is empty, not open.
            return "1=0", []
        return "d.client_id = %s", [client_id]

    role = user.get("role")
    if role in STAFF_ROLE_HIERARCHY and role not in CLIENT_ROLES:
        # Staff: all knowledge, no client records.
        return "d.client_id IS NULL", []

    return "1=0", []


def get_version_filter(is_approved: bool = True, is_active: bool = True) -> tuple[str, list]:
    """Build the active-version filter clause.

    Only returns approved + active chunks by default. This is also what
    makes admin approval a real gate: ingestion writes ``is_approved =
    false``, so an uploaded document is unreachable — including by whoever
    uploaded it — until an admin approves it.
    """
    conditions: list[str] = []
    params: list = []

    if is_approved:
        conditions.append("c.is_approved = true")
    if is_active:
        conditions.append("c.is_active = true")

    clause = " AND ".join(conditions) if conditions else "(true)"
    return clause, params
