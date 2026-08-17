"""Unit tests for the RBAC search filter — the primary enforcement point.

``metadata_filters.get_search_filter`` builds the WHERE fragment that
decides which documents a user can retrieve. Per CLAUDE.md rule 1 this is
the *only* place that decision is made, so every branch is tested here.

The boundary is client ownership, not department. A processor may read any
document that belongs to no client; a client may read only their own. That
is the whole model, and the tests below are written to fail loudly if it
ever silently widens.
"""

from __future__ import annotations

import pytest

from app.search.metadata_filters import get_search_filter

ADMIN = {"role": "admin", "department": "general", "allowed_departments": []}
SUPER_ADMIN = {"role": "super_admin", "department": "general", "allowed_departments": []}
PROCESSOR = {"role": "processor", "department": "general", "allowed_departments": []}
CLIENT = {"role": "client", "department": "general", "client_id": "CLIENT_A"}
CLIENT_NO_ID = {"role": "client", "department": "general", "client_id": None}


class TestAdmin:
    def test_admin_is_unfiltered(self):
        assert get_search_filter(ADMIN) == ("", [])

    def test_super_admin_is_unfiltered(self):
        assert get_search_filter(SUPER_ADMIN) == ("", [])


class TestProcessor:
    def test_unassigned_processor_is_restricted_to_documents_with_no_client(self):
        """The guard that makes client records safe to add: opening
        knowledge to all staff must not open client files with it. An
        unassigned processor's `assigned_clients` is empty, and
        `= ANY('{}')` is always false in Postgres, so this degrades to
        exactly the pre-Stage-2 clause -- no special-casing needed."""
        clause, params = get_search_filter(PROCESSOR)
        assert clause == "(d.client_id IS NULL OR d.client_id = ANY(%s))"
        assert params == [[]]

    def test_assigned_processor_reaches_their_assigned_clients_too(self):
        """Stage 2, Task 7: self-assignment (/me/clients) is the only path
        from processor to a client's documents."""
        assigned = {**PROCESSOR, "assigned_clients": ["CLIENT_A", "CLIENT_B"]}
        clause, params = get_search_filter(assigned)
        assert clause == "(d.client_id IS NULL OR d.client_id = ANY(%s))"
        assert params == [["CLIENT_A", "CLIENT_B"]]

    def test_assignment_to_one_client_does_not_expose_another(self):
        """The ANY(%s) list is exactly assigned_clients -- nothing wider."""
        assigned = {**PROCESSOR, "assigned_clients": ["CLIENT_A"]}
        _, params = get_search_filter(assigned)
        assert "CLIENT_B" not in params[0]

    def test_processor_is_not_filtered_by_department(self):
        """Department is organisational metadata now, not a gate -- staff
        must not have to ask an admin for access to reach a document."""
        clause, _ = get_search_filter(PROCESSOR)
        assert "department" not in clause

    def test_department_does_not_change_the_clause(self):
        """Two processors in different departments see the same thing."""
        other = {**PROCESSOR, "department": "underwriting"}
        assert get_search_filter(PROCESSOR) == get_search_filter(other)

    def test_allowed_departments_are_irrelevant(self):
        granted = {**PROCESSOR, "allowed_departments": ["compliance", "servicing"]}
        assert get_search_filter(granted) == get_search_filter(PROCESSOR)


class TestClient:
    def test_client_sees_only_their_own_documents(self):
        clause, params = get_search_filter(CLIENT)
        assert clause == "d.client_id = %s"
        assert params == ["CLIENT_A"]

    def test_client_without_an_id_is_denied_everything(self):
        assert get_search_filter(CLIENT_NO_ID) == ("1=0", [])

    def test_client_cannot_reach_unowned_documents(self):
        """A client must not inherit the processor's open-knowledge rule."""
        clause, _ = get_search_filter(CLIENT)
        assert "IS NULL" not in clause


class TestFailsClosed:
    def test_no_user_is_denied_everything(self):
        """Search requires auth, but the filter must not be the thing that
        assumes it: an absent user previously fell through to a deny-all and
        must continue to."""
        assert get_search_filter(None) == ("1=0", [])

    @pytest.mark.parametrize("role", ["", "loan_officer", "auditor", "ADMIN", None])
    def test_unrecognized_roles_are_denied(self, role):
        """A typo, or a row that escaped the role migration, must be denied
        rather than treated as a processor and handed the whole knowledge
        base. Mirrors require_role, which also fails closed."""
        clause, params = get_search_filter(
            {"role": role, "department": "general", "allowed_departments": []}
        )
        assert clause == "1=0"
        assert params == []

    def test_role_key_missing_entirely_is_denied(self):
        assert get_search_filter({"department": "general"}) == ("1=0", [])


class TestSingleEnforcementPoint:
    def test_rbac_module_no_longer_defines_a_second_filter(self):
        """Two diverged copies of this function existed, and only one was
        wired in. Keeping them apart is how they drifted."""
        from app.auth import rbac

        assert not hasattr(rbac, "get_search_filter")

    def test_orchestrator_uses_the_metadata_filters_implementation(self):
        from app.search import hybrid_orchestrator
        from app.search import metadata_filters

        assert hybrid_orchestrator.get_search_filter is (
            metadata_filters.get_search_filter
        )
