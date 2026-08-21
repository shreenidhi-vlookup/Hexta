"""Unit tests for the GraphRAG-lite entity channel.

Covers both ends of chunk_entity_links:

1. Ingestion (documents/indexing.py) must harvest chunk→entity edges
   from dictionary extraction and write them in the same transaction as
   the chunk itself. A missing edge silently degrades retrieval quality
   rather than raising, so this is the only place it can be caught.
2. Query time (search/hybrid_orchestrator.py) must join the links as a
   third RRF channel keyed on canonical query entities — and contribute
   nothing when the query names no known entity.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.documents.chunking.structural_chunker import Chunk
from app.documents.indexing import index_document
from app.search.hybrid_orchestrator import search_knowledge_base


def _mock_conn(document_id: int = 1):
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = {"id": document_id}
    cur.rowcount = 1
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


def _chunk(content: str) -> Chunk:
    return Chunk(
        content=content,
        section="Core Terms",
        chunk_type="definition",
        page_number=None,
    )


def _calls(cur, needle: str):
    return [c[0] for c in cur.execute.call_args_list if needle in c[0][0]] + [
        c[0] for c in cur.executemany.call_args_list if needle in c[0][0]
    ]


class TestIngestionEntityLinks:
    def test_links_are_harvested_for_domain_content(self):
        conn, cur = _mock_conn()
        index_document(
            conn=conn, doc_title="T", doc_type="policy", department="general",
            source_path="p.txt",
            chunks=[_chunk("An FHA loan is insured by the government.")],
        )
        link_calls = _calls(cur, "INSERT INTO chunk_entity_links")
        assert len(link_calls) == 1
        rows = link_calls[0][1]
        # Edges store the *canonical* term, so any alias of the same
        # entity resolves to the same links at query time.
        assert all(
            r[1] == "federal housing administration" and r[2] == "lender"
            for r in rows
        )

    def test_no_entities_means_no_link_writes(self):
        conn, cur = _mock_conn()
        index_document(
            conn=conn, doc_title="T", doc_type="policy", department="general",
            source_path="p.txt",
            chunks=[_chunk("Plain prose with no recognized domain vocabulary at all.")],
        )
        assert _calls(cur, "INSERT INTO chunk_entity_links") == []

    def test_duplicate_chunk_is_not_relinked(self):
        """A content-hash duplicate inserts no row, so it must not spawn
        entity edges either (fetchone returns None via ON CONFLICT DO
        NOTHING RETURNING)."""
        conn, cur = _mock_conn()
        # First fetchone -> documents id; second -> None (conflict).
        cur.fetchone.side_effect = [{"id": 9}, None]
        index_document(
            conn=conn, doc_title="T", doc_type="policy", department="general",
            source_path="p.txt",
            chunks=[_chunk("An FHA loan is insured by the government.")],
        )
        assert _calls(cur, "INSERT INTO chunk_entity_links") == []


class TestQueryTimeEntityChannel:
    def test_entity_join_present_in_sql(self):
        conn, cur = _mock_conn()
        search_knowledge_base(conn=conn, sub_queries=["fha loans"], user=None)
        query, params = cur.execute.call_args[0]
        assert "chunk_entity_links" in query
        assert "= ANY(%s)" in query
        # Canonical query entities are passed as the array parameter —
        # the alias "fha" resolves to its canonical form.
        assert any(
            isinstance(p, list) and "federal housing administration" in p
            for p in params
        )

    def test_placeholder_count_still_matches_with_entity_channel(self):
        conn, cur = _mock_conn()
        search_knowledge_base(
            conn=conn,
            sub_queries=["fha vs va down payment"],
            user={"role": "client", "department": "general", "client_id": "CLIENT_A"},
        )
        query, params = cur.execute.call_args[0]
        assert query.count("%s") == len(params)

    def test_entity_channel_has_case_guard(self):
        """Chunks with zero entity hits must not receive fusion weight."""
        conn, cur = _mock_conn()
        search_knowledge_base(conn=conn, sub_queries=["credit score"], user=None)
        query, _ = cur.execute.call_args[0]
        assert "CASE WHEN COALESCE(entity_hits, 0) > 0" in query

    def test_empty_sub_queries_short_circuits(self):
        conn, cur = _mock_conn()
        result = search_knowledge_base(conn=conn, sub_queries=[], user=None)
        assert result.candidates == []
        cur.execute.assert_not_called()
