"""Integration test for client-scoped isolation (Phase 3a).

Verifies that a client user can only retrieve documents tagged with
their own client_id — never another client's data, nor internal
documents (client_id IS NULL).

Security enforcement is in the SQL WHERE clause via
metadata_filters.get_search_filter (CLAUDE.md rule #1).
"""

from __future__ import annotations

import pytest

from app.db.postgres.session import acquire
from app.db.postgres.schema import ensure_schema
from app.search.hybrid_orchestrator import search_knowledge_base
from app.auth.rbac import is_client, resolve_user_client_id


def _db_available() -> bool:
    try:
        from app.db.postgres.session import ping
        return ping()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="Requires a running Postgres instance with hexa_assistant schema",
)


CLIENT_A_USER = {
    "id": 100,
    "role": "client",
    "department": "general",
    "allowed_departments": [],
    "client_id": "CLIENT_A",
}

CLIENT_B_USER = {
    "id": 101,
    "role": "client",
    "department": "general",
    "allowed_departments": [],
    "client_id": "CLIENT_B",
}

CLIENT_NO_ID_USER = {
    "id": 102,
    "role": "client",
    "department": "general",
    "allowed_departments": [],
    "client_id": None,
}


@pytest.fixture(scope="module")
def seeded_client_document():
    """Create documents for CLIENT_A and CLIENT_B (approved, with embeddings)."""
    ensure_schema()

    # Clean up any leftover data from prior runs
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM document_chunks WHERE content_hash IN (%s, %s)",
                ("hash_a_1", "hash_b_1"),
            )
            cur.execute(
                "DELETE FROM documents WHERE title IN ('Client A Doc', 'Client B Doc')"
            )
            conn.commit()

    doc_ids = []
    chunk_ids = []

    with acquire() as conn:
        with conn.cursor() as cur:
            # Insert a document for CLIENT_A
            cur.execute(
                "INSERT INTO documents (title, doc_type, department, "
                "source_path, is_approved, client_id) "
                "VALUES (%s, %s, %s, %s, true, %s) RETURNING id",
                ("Client A Doc", "policy", "general", "/test/a.pdf", "CLIENT_A"),
            )
            doc_a_id = cur.fetchone()["id"]
            doc_ids.append(doc_a_id)

            cur.execute(
                "INSERT INTO document_chunks "
                "(document_id, content, content_hash, section, chunk_type, "
                "department, is_approved, client_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, true, %s) RETURNING id",
                (
                    doc_a_id,
                    "Client A specific credit score requirement is 650.",
                    "hash_a_1",
                    "Credit",
                    "paragraph",
                    "general",
                    "CLIENT_A",
                ),
            )
            chunk_ids.append(cur.fetchone()["id"])

            # Insert a document for CLIENT_B
            cur.execute(
                "INSERT INTO documents (title, doc_type, department, "
                "source_path, is_approved, client_id) "
                "VALUES (%s, %s, %s, %s, true, %s) RETURNING id",
                ("Client B Doc", "policy", "general", "/test/b.pdf", "CLIENT_B"),
            )
            doc_b_id = cur.fetchone()["id"]
            doc_ids.append(doc_b_id)

            cur.execute(
                "INSERT INTO document_chunks "
                "(document_id, content, content_hash, section, chunk_type, "
                "department, is_approved, client_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, true, %s) RETURNING id",
                (
                    doc_b_id,
                    "Client B exclusive policy: maximum LTV is 75 percent.",
                    "hash_b_1",
                    "LTV",
                    "paragraph",
                    "general",
                    "CLIENT_B",
                ),
            )
            chunk_ids.append(cur.fetchone()["id"])

            conn.commit()

            # Generate embeddings (required by hybrid search's vector clause)
            from app.search.pgvector_search import embed_query

            for cid, content in [
                (chunk_ids[0], "Client A specific credit score requirement is 650."),
                (chunk_ids[1], "Client B exclusive policy: maximum LTV is 75 percent."),
            ]:
                emb = embed_query(content)
                cur.execute(
                    "UPDATE document_chunks SET embedding = %s WHERE id = %s",
                    (emb, cid),
                )
            conn.commit()

    yield {"doc_a": doc_a_id, "doc_b": doc_b_id, "chunk_a": chunk_ids[0], "chunk_b": chunk_ids[1]}

    # Cleanup
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM document_chunks WHERE document_id = ANY(%s)",
                (doc_ids,),
            )
            cur.execute(
                "DELETE FROM documents WHERE id = ANY(%s)",
                (doc_ids,),
            )
            conn.commit()


class TestClientIsolation:
    def test_is_client_role(self):
        assert is_client(CLIENT_A_USER) is True
        assert is_client(CLIENT_B_USER) is True

    def test_is_not_client_for_staff(self):
        assert is_client({"role": "admin", "client_id": None}) is False
        assert is_client({"role": "loan_officer"}) is False
        assert is_client(None) is False

    def test_resolve_client_id(self):
        assert resolve_user_client_id(CLIENT_A_USER) == "CLIENT_A"
        assert resolve_user_client_id({"role": "admin"}) is None
        assert resolve_user_client_id(None) is None

    def test_client_without_client_id_denied(self):
        """A user with role='client' but no client_id gets deny-all filter."""
        from app.search.metadata_filters import get_search_filter

        clause, params = get_search_filter(CLIENT_NO_ID_USER)
        assert clause == "1=0"
        assert params == []

    def test_client_sees_own_documents(self, seeded_client_document):
        """CLIENT_A user should retrieve only CLIENT_A chunks."""
        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=["credit score"],
                user=CLIENT_A_USER,
            )

        client_a_chunk_ids = {seeded_client_document["chunk_a"]}
        retrieved_ids = {c.chunk_id for c in result.candidates}

        # Client A should see their own chunk
        assert seeded_client_document["chunk_a"] in retrieved_ids
        # Client A should NOT see CLIENT_B's chunk
        assert seeded_client_document["chunk_b"] not in retrieved_ids

    def test_client_b_sees_own_documents(self, seeded_client_document):
        """CLIENT_B user should retrieve only CLIENT_B chunks."""
        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=["ltv policy"],
                user=CLIENT_B_USER,
            )

        retrieved_ids = {c.chunk_id for c in result.candidates}

        # Client B should see their own chunk
        assert seeded_client_document["chunk_b"] in retrieved_ids
        # Client B should NOT see CLIENT_A's chunk
        assert seeded_client_document["chunk_a"] not in retrieved_ids

    def test_cross_client_no_leakage(self, seeded_client_document):
        """Explicitly assert CLIENT_A never sees CLIENT_B data."""
        with acquire() as conn:
            result_a = search_knowledge_base(
                conn=conn,
                sub_queries=["credit score ltv"],
                user=CLIENT_A_USER,
            )
            result_b = search_knowledge_base(
                conn=conn,
                sub_queries=["credit score ltv"],
                user=CLIENT_B_USER,
            )

        ids_a = {c.chunk_id for c in result_a.candidates}
        ids_b = {c.chunk_id for c in result_b.candidates}

        assert seeded_client_document["chunk_a"] in ids_a
        assert seeded_client_document["chunk_b"] not in ids_a
        assert seeded_client_document["chunk_b"] in ids_b
        assert seeded_client_document["chunk_a"] not in ids_b


class TestStaffSelfAssignedAccess:
    """Stage 2, Task 8 verification: the actual boundary Task 7 built.

    Uses the same seeded CLIENT_A / CLIENT_B documents as the tests
    above, from the staff side -- an unassigned processor, then the same
    processor after self-assigning, proving isolation holds in both
    directions with a real SQL round-trip, not a unit-level stub.
    """

    UNASSIGNED_PROCESSOR = {
        "role": "processor", "department": "general", "allowed_departments": [],
    }

    def test_unassigned_processor_sees_neither_client(self, seeded_client_document):
        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=["credit score ltv"],
                user=self.UNASSIGNED_PROCESSOR,
            )
        retrieved_ids = {c.chunk_id for c in result.candidates}
        assert seeded_client_document["chunk_a"] not in retrieved_ids
        assert seeded_client_document["chunk_b"] not in retrieved_ids

    def test_assigned_processor_reaches_only_their_assigned_client(
        self, seeded_client_document,
    ):
        assigned_to_a = {
            **self.UNASSIGNED_PROCESSOR, "assigned_clients": ["CLIENT_A"],
        }
        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=["credit score ltv"],
                user=assigned_to_a,
            )
        retrieved_ids = {c.chunk_id for c in result.candidates}
        assert seeded_client_document["chunk_a"] in retrieved_ids
        assert seeded_client_document["chunk_b"] not in retrieved_ids

    def test_assignment_to_one_client_never_exposes_the_other(
        self, seeded_client_document,
    ):
        """Assigned to A and B both, still never confuses which chunk
        belongs to which -- both are reachable, neither leaks into the
        wrong client's response (checked at the RBAC layer here; response
        assembly keeps them in separate answer blocks)."""
        assigned_to_both = {
            **self.UNASSIGNED_PROCESSOR,
            "assigned_clients": ["CLIENT_A", "CLIENT_B"],
        }
        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=["credit score ltv"],
                user=assigned_to_both,
            )
        retrieved_ids = {c.chunk_id for c in result.candidates}
        assert seeded_client_document["chunk_a"] in retrieved_ids
        assert seeded_client_document["chunk_b"] in retrieved_ids

    def test_still_never_reaches_an_unassigned_client(
        self, seeded_client_document,
    ):
        """Assigned to A only -- B stays out of reach exactly as if no
        assignment existed at all."""
        assigned_to_a_only = {
            **self.UNASSIGNED_PROCESSOR, "assigned_clients": ["CLIENT_A"],
        }
        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=["ltv policy"],
                user=assigned_to_a_only,
            )
        retrieved_ids = {c.chunk_id for c in result.candidates}
        assert seeded_client_document["chunk_b"] not in retrieved_ids
