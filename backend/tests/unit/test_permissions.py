"""Unit tests for require_role — must fail closed on any role it doesn't
recognize as staff (CLAUDE.md rule #1: RBAC is enforced, never bypassed).

Regression coverage for a bug where a client-scoped role (or any typo'd /
unrecognized role) slipped through require_role's ValueError fallback and
was silently granted access to every admin-gated endpoint.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth import rbac
from app.auth.permissions import require_role


class TestRoleTaxonomyStaysInSync:
    """Regression guard for the role-hierarchy duplication that caused the
    'client' bypass: STAFF_ROLE_HIERARCHY and CLIENT_ROLES (rbac.py) must
    always cover every role in ROLE_DEPARTMENTS, or a newly-added role
    could again fall through require_role() unhandled."""

    def test_every_role_is_covered_by_hierarchy_or_client_roles(self):
        covered = set(rbac.STAFF_ROLE_HIERARCHY) | rbac.CLIENT_ROLES
        assert covered == set(rbac.ROLE_DEPARTMENTS)

    def test_permissions_module_uses_the_shared_hierarchy(self):
        """permissions.py must not redefine its own hierarchy list."""
        from app.auth import permissions

        assert permissions._HIERARCHY is rbac.STAFF_ROLE_HIERARCHY


class TestRequireRoleFailsClosed:
    def test_client_role_is_denied_admin(self):
        """A 'client' user must never pass an admin-role check."""
        with pytest.raises(HTTPException) as exc:
            require_role({"role": "client"}, "admin")
        assert exc.value.status_code == 403

    def test_unrecognized_role_is_denied(self):
        """A role string outside the known hierarchy must be denied, not
        silently admitted (the original bug: ValueError -> return)."""
        with pytest.raises(HTTPException) as exc:
            require_role({"role": "totally-made-up-role"}, "admin")
        assert exc.value.status_code == 403

    def test_missing_user_is_denied_admin(self):
        with pytest.raises(HTTPException) as exc:
            require_role(None, "admin")
        assert exc.value.status_code == 403

    def test_loan_officer_is_denied_admin(self):
        with pytest.raises(HTTPException) as exc:
            require_role({"role": "loan_officer"}, "admin")
        assert exc.value.status_code == 403

    def test_admin_passes_admin_check(self):
        require_role({"role": "admin"}, "admin")  # must not raise

    def test_super_admin_passes_admin_check(self):
        require_role({"role": "super_admin"}, "admin")  # must not raise
