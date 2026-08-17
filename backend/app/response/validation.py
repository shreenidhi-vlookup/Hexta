"""Response validation — redundant safety-net check (CLAUDE.md rule #1).

The PRIMARY enforcement is in search/hybrid_orchestrator.py WHERE clause.
This module re-checks permissions and version flags as a safety net.

Confidence-based routing is handled by
``response/confidence_thresholds.py`` (``route_by_confidence``) — it sets
``package.routing`` to ``"answer"``, ``"partial"``, or ``"no_answer"``;
validation must NOT treat low confidence as a hard failure, otherwise
every "no answer found" query returns HTTP 500 instead of a graceful
``no_answer`` response.
"""

from __future__ import annotations

from app.auth.rbac import (
    is_admin,
    is_client,
    resolve_user_assigned_clients,
    resolve_user_client_id,
)
from app.response.package_builder import ResponsePackage


def validate_package(
    package: ResponsePackage,
    user: dict | None,
    min_confidence: float = 50.0,
    ) -> tuple[bool, str]:
    """Validate a response package against RBAC and version rules.

    Returns (valid, reason). If invalid, the package should not be returned
    to the user.

    Confidence is **not** checked here — that is the job of
    ``route_by_confidence``, which decides ``package.routing``.
    Low-confidence results are valid responses that the caller routes to
    ``"no_answer"`` or ``"partial"``, not server errors.
    """
    # RBAC check — safety net (primary enforcement is in the SQL WHERE clause,
    # search/metadata_filters.py). This mirrors that rule and must be kept in
    # step with it: the two previously disagreed, because this one still
    # enforced department after the primary filter moved to client ownership,
    # and a processor legitimately retrieving a document from another
    # department had their response rejected as an RBAC violation — surfacing
    # as an HTTP 500 rather than an answer.
    if user is not None and not is_admin(user):
        # Client scope: clients see only their own data.
        user_client_id = resolve_user_client_id(user)
        if is_client(user):
            for excerpt in package.excerpts:
                if excerpt.source.client_id != user_client_id:
                    return False, (
                        f"RBAC violation: chunk {excerpt.source.chunk_id} "
                        f"belongs to client_id '{excerpt.source.client_id}', "
                        f"not '{user_client_id}'"
                    )
        else:
            # Staff: knowledge (no client), plus any client they have
            # self-assigned to (/me/clients, api/v1/me.py). Must stay in
            # lockstep with metadata_filters.py's staff branch -- the two
            # disagreed once already (this file still enforced the retired
            # department rule after the primary filter moved to client
            # ownership) and a legitimate retrieval surfaced as an HTTP 500
            # instead of an answer.
            assigned_clients = resolve_user_assigned_clients(user)
            for excerpt in package.excerpts:
                chunk_client_id = excerpt.source.client_id
                if chunk_client_id is not None and chunk_client_id not in assigned_clients:
                    return False, (
                        f"RBAC violation: chunk {excerpt.source.chunk_id} "
                        f"belongs to client_id '{chunk_client_id}', not "
                        "assigned to this staff member"
                    )

    # Version and approval check — safety net
    for excerpt in package.excerpts:
        if not excerpt.source.is_approved:
            return False, (
                f"Response safety violation: chunk {excerpt.source.chunk_id} "
                "is not approved"
            )
        if excerpt.source.document_version < 1:
            return False, (
                f"Response safety violation: document {excerpt.source.document_id} "
                f"has invalid version {excerpt.source.document_version}"
            )

    return True, "OK"
