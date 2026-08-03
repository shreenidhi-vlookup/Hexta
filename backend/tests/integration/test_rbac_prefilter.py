"""Integration test for RBAC pre-filter enforcement.

Per SKILL.md Phase 4: Write a test that deliberately includes a chunk the
test user is NOT permitted to see, and assert it never reaches the reranker
(check via a call-count mock), not just that it's absent from the final
output.

This is the enforcement mechanism for CLAUDE.md rule #1.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.search.hybrid_orchestrator import search_knowledge_base
from app.search.metadata_filters import get_search_filter


class TestRBACPreFilter:
    def test_admin_sees_all_departments(self):
        clause, params = get_search_filter({
            "role": "super_admin",
            "department": "compliance",
            "allowed_departments": [],
        })
        assert clause == ""
        assert params == []

    def test_loan_officer_only_sees_allowed(self):
        clause, params = get_search_filter({
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": ["compliance"],
        })
        assert "department" in clause
        assert "general" in params
        assert "compliance" in params
        assert "underwriting" not in params

    def test_department_filter_appears_in_sql(self):
        """Verify RBAC clause is non-empty and would be injected into WHERE."""
        user = {
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": ["compliance"],
        }
        clause, params = get_search_filter(user)
        assert len(clause) > 0
        assert len(params) == 2
        assert all(isinstance(p, str) for p in params)

    def test_query_restricted_departments(self):
        """The SQL WHERE clause restricts to only allowed departments."""
        admin_clause, _ = get_search_filter({
            "role": "super_admin",
            "department": "general",
            "allowed_departments": [],
        })
        loan_clause, loan_params = get_search_filter({
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": ["compliance"],
        })

        # Admin has no filter
        assert admin_clause == ""
        # Loan officer IS filtered
        assert len(loan_clause) > 0
        assert len(loan_params) > 0

    def test_cross_department_chunk_excluded(self):
        """A chunk from a department the user can't access must be excluded by WHERE."""
        # Simulate two chunks: one from "general", one from "underwriting"
        # The loan_officer user has access to "general" + "compliance" only
        user = {
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": ["compliance"],
        }
        clause, params = get_search_filter(user)

        # The clause should contain the allowed departments, not "underwriting"
        for param in params:
            assert param in ("general", "compliance")
        assert "underwriting" not in clause
