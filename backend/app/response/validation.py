"""Response validation — redundant safety-net check (CLAUDE.md rule #1).

The PRIMARY enforcement is in search/hybrid_orchestrator.py WHERE clause.
This module re-checks permissions and version flags as a safety net.
"""

from __future__ import annotations

from app.auth.rbac import is_admin, resolve_user_departments
from app.response.package_builder import ResponsePackage


def validate_package(
    package: ResponsePackage,
    user: dict | None,
    min_confidence: float = 50.0,
) -> tuple[bool, str]:
    """Validate a response package against RBAC and confidence thresholds.

    Returns (valid, reason). If invalid, the package should not be returned
    to the user.
    """
    # Confidence check
    if package.confidence < min_confidence:
        return False, f"Confidence {package.confidence}% below threshold {min_confidence}%"

    # RBAC check — safety net
    if user is not None and not is_admin(user):
        user_depts = set(resolve_user_departments(user))
        for excerpt in package.excerpts:
            if excerpt.source.department and excerpt.source.department not in user_depts:
                return False, f"RBAC violation: chunk from department '{excerpt.source.department}' not visible to user"

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
