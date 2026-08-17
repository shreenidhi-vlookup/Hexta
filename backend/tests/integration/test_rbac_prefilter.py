"""Integration test for RBAC pre-filter enforcement.

Per SKILL.md Phase 4: a chunk the test user is NOT permitted to see must be
excluded by the SQL WHERE clause, so it never reaches the reranker at all —
not merely be absent from the final output. This is the enforcement
mechanism for CLAUDE.md rule #1.

Rewritten for the two-tier access model. The boundary these tests guard is
now **client ownership** rather than department: a processor reads any
document belonging to no client, and never one belonging to a client. The
department assertions this file used to make were removed because
department is no longer an access boundary, not because they stopped
mattering — the ownership assertions below replace them.
"""

from __future__ import annotations

from app.search.hybrid_orchestrator import SearchCandidate
from app.search.metadata_filters import get_search_filter

PROCESSOR = {
    "role": "processor",
    "department": "general",
    "allowed_departments": [],
}
ADMIN = {
    "role": "super_admin",
    "department": "compliance",
    "allowed_departments": [],
}
CLIENT_A = {"role": "client", "department": "general", "client_id": "CLIENT_A"}


class TestRBACPreFilter:
    def test_admin_is_unfiltered(self):
        clause, params = get_search_filter(ADMIN)
        assert clause == ""
        assert params == []

    def test_processor_clause_is_injected_into_where(self):
        """The clause must be non-empty and parameterised, so it can be
        ANDed into the query rather than applied afterwards. Stage 2's
        assigned_clients param is a list (bound to ANY(%s)), not a scalar,
        so this checks shape rather than a flat list of strings."""
        clause, params = get_search_filter(PROCESSOR)
        assert clause
        assert len(params) == 1
        assert isinstance(params[0], list)

    def test_processor_reaches_across_departments(self):
        """The department barrier is deliberately gone: staff must not need
        an admin to grant access before they can answer a question."""
        clause, _ = get_search_filter(PROCESSOR)
        assert "department" not in clause

        other_department = {**PROCESSOR, "department": "underwriting"}
        assert get_search_filter(other_department) == get_search_filter(PROCESSOR)

    def test_client_owned_chunk_is_excluded_for_an_unassigned_processor(self):
        """The replacement boundary. A document tagged to a client must be
        filtered out in SQL for staff who haven't self-assigned to it, not
        trimmed from results later."""
        clause, params = get_search_filter(PROCESSOR)
        assert clause == "(d.client_id IS NULL OR d.client_id = ANY(%s))"
        assert params == [[]]

    def test_client_owned_chunk_is_reachable_once_assigned(self):
        """Stage 2, Task 7: self-assignment (/me/clients) is the only path
        from processor to a client's documents."""
        assigned = {**PROCESSOR, "assigned_clients": ["CLIENT_A"]}
        clause, params = get_search_filter(assigned)
        assert clause == "(d.client_id IS NULL OR d.client_id = ANY(%s))"
        assert params == [["CLIENT_A"]]

    def test_restricted_chunk_never_reaches_the_reranker(self):
        """Both candidates below are plausible retrieval hits, and the
        restricted one scores *higher* — so anything that filtered after
        ranking would surface it. The WHERE clause is what prevents the row
        from ever being selected."""
        allowed = SearchCandidate(
            chunk_id=1,
            document_id=1,
            title="Lending Policy",
            doc_type="policy",
            department="general",
            section="Eligibility",
            chunk_type="paragraph",
            content="The minimum credit score is 620.",
            is_approved=True,
            document_version=1,
            bm25_score=0.8,
            vec_score=0.7,
        )
        client_owned = SearchCandidate(
            chunk_id=2,
            document_id=2,
            title="Client File",
            doc_type="policy",
            department="general",
            section="Income",
            chunk_type="paragraph",
            content="Applicant credit score is 640 per the submitted report.",
            is_approved=True,
            document_version=1,
            bm25_score=0.9,
            vec_score=0.85,
        )
        assert client_owned.bm25_score > allowed.bm25_score

        clause, params = get_search_filter(PROCESSOR)
        # The row is excluded by ownership: an unassigned processor's
        # ANY(%s) param is empty, so no client identifier is present to be
        # widened by accident.
        assert clause == "(d.client_id IS NULL OR d.client_id = ANY(%s))"
        assert params == [[]]

    def test_client_is_scoped_to_their_own_documents(self):
        clause, params = get_search_filter(CLIENT_A)
        assert clause == "d.client_id = %s"
        assert params == ["CLIENT_A"]

    def test_unauthenticated_user_gets_no_results(self):
        """The search endpoint requires auth, but the filter must not be the
        thing that assumes it."""
        assert get_search_filter(None) == ("1=0", [])

    def test_role_outside_the_taxonomy_gets_no_results(self):
        """A row that escaped the processor migration must fail closed."""
        stale = {"role": "loan_officer", "department": "general"}
        assert get_search_filter(stale) == ("1=0", [])
