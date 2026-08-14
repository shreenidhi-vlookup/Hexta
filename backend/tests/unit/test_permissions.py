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
    'client' bypass. The invariant require_role actually depends on is that
    the staff ladder and the client track never overlap: a role in both
    would be ranked *and* denied, and which one wins is an accident of
    ordering inside require_role."""

    def test_staff_and_client_tracks_are_disjoint(self):
        assert not (set(rbac.STAFF_ROLE_HIERARCHY) & rbac.CLIENT_ROLES)

    def test_admin_roles_are_part_of_the_staff_ladder(self):
        """ADMIN_ROLES gates search filtering; a role there but missing from
        the ladder would bypass RBAC while failing every require_role."""
        assert rbac.ADMIN_ROLES <= set(rbac.STAFF_ROLE_HIERARCHY)

    def test_permissions_module_uses_the_shared_hierarchy(self):
        """permissions.py must not redefine its own hierarchy list."""
        from app.auth import permissions

        assert permissions._HIERARCHY is rbac.STAFF_ROLE_HIERARCHY


class TestTwoTierRoleModel:
    """The role model is deliberately two staff tiers plus super_admin:
    'processor' does the work, 'admin' manages and approves."""

    def test_processor_is_the_base_staff_role(self):
        assert rbac.STAFF_ROLE_HIERARCHY[0] == "processor"

    def test_retired_roles_are_gone(self):
        """Left behind, they would still pass require_role and quietly
        outrank processor."""
        for retired in ("loan_officer", "underwriter", "compliance"):
            assert retired not in rbac.STAFF_ROLE_HIERARCHY

    def test_processor_is_denied_admin_actions(self):
        with pytest.raises(HTTPException) as exc:
            require_role({"role": "processor"}, "admin")
        assert exc.value.status_code == 403

    def test_processor_passes_a_processor_check(self):
        require_role({"role": "processor"}, "processor")  # must not raise

    def test_admin_passes_a_processor_check(self):
        """Higher tiers inherit lower scopes, so admins can upload too."""
        require_role({"role": "admin"}, "processor")

    def test_retired_role_is_denied_rather_than_ranked(self):
        """A user row that somehow escaped the migration must fail closed,
        not be treated as an unknown-but-allowed staff member."""
        with pytest.raises(HTTPException) as exc:
            require_role({"role": "loan_officer"}, "processor")
        assert exc.value.status_code == 403


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
