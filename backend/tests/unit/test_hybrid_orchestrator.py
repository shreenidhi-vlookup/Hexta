"""Unit tests for search/hybrid_orchestrator.py's SQL construction.

Regression coverage for two related bugs fixed together:

1. The WHERE clause used to require BM25 lexeme overlap
   (c.fts @@ to_tsquery(...)) unconditionally, which excluded a chunk
   entirely whenever a well-formed, correctly-spelled query shared no
   vocabulary with it — pgvector's semantic match never got a chance,
   defeating the point of "hybrid" search.
2. Fixing #1 by dropping the gate outright is unsafe: without any floor,
   a query with literally no relevant content in the KB still always
   retrieves *something* (whatever's nearest in embedding space), which
   downstream RRF/confidence logic can inflate into a false answer. The
   fix instead admits a chunk if EITHER it has BM25 overlap OR its vector
   similarity alone clears ranking.weights_config.DEFAULT_WEIGHTS
   .min_vector_similarity.

These tests mock the DB connection/cursor — no live Postgres needed — and
assert on the SQL text and the parameter list's shape, since the query is
hand-assembled from parts and a mismatched %s-vs-params count would only
surface as a runtime psycopg error, not a Python-level one.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.ranking.weights_config import DEFAULT_WEIGHTS
from app.search.hybrid_orchestrator import search_knowledge_base


def _scalar_params(params):
    """params includes the embedding vector (a numpy array) alongside
    scalar values — `x in params` raises ValueError on array elements
    ("truth value of an array... is ambiguous"), so scalar-membership
    checks must filter those out first."""
    return [p for p in params if isinstance(p, (str, int, float))]


def _mock_conn(rows=None):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = rows or []
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    conn.cursor.return_value = cur
    return conn, cur


class TestQueryParamAlignment:
    """The number of %s placeholders in the query must exactly match the
    params list length, and BM25/vector-similarity params must be
    positioned correctly relative to the WHERE clause they gate."""

    def test_placeholder_count_matches_param_count_no_rbac(self):
        conn, cur = _mock_conn()
        search_knowledge_base(conn=conn, sub_queries=["credit score"], user=None)
        query, params = cur.execute.call_args[0]
        assert query.count("%s") == len(params)

    def test_processor_rbac_clause_reaches_the_query(self):
        """A processor's clause carries no parameters of its own, so the
        only evidence it was applied is the SQL text itself."""
        conn, cur = _mock_conn()
        user = {
            "role": "processor",
            "department": "general",
            "allowed_departments": [],
        }
        search_knowledge_base(conn=conn, sub_queries=["credit score"], user=user)
        query, params = cur.execute.call_args[0]
        assert query.count("%s") == len(params)
        assert "d.client_id IS NULL" in query

    def test_placeholder_count_matches_param_count_with_rbac(self):
        """A client's clause *does* contribute a parameter, which is the
        case where placeholder/param alignment can actually break."""
        conn, cur = _mock_conn()
        user = {
            "role": "client",
            "department": "general",
            "client_id": "CLIENT_A",
        }
        search_knowledge_base(conn=conn, sub_queries=["credit score"], user=user)
        query, params = cur.execute.call_args[0]
        assert query.count("%s") == len(params)
        # The RBAC param must actually be present in the final params list.
        assert "CLIENT_A" in _scalar_params(params)

    def test_where_clause_does_not_hard_gate_on_bm25(self):
        """Regression: c.fts @@ to_tsquery(...) must not be an unconditional
        top-level WHERE AND-term — it must only appear inside an OR with
        the vector-similarity floor."""
        conn, cur = _mock_conn()
        search_knowledge_base(conn=conn, sub_queries=["credit score"], user=None)
        query, _ = cur.execute.call_args[0]
        where_clause = query.split("WHERE", 1)[1].split("ORDER BY", 1)[0]
        assert "OR (1 - (c.embedding <=> %s)) >= %s" in where_clause

    def test_vector_similarity_threshold_is_passed(self):
        conn, cur = _mock_conn()
        search_knowledge_base(conn=conn, sub_queries=["credit score"], user=None)
        _, params = cur.execute.call_args[0]
        assert DEFAULT_WEIGHTS.min_vector_similarity in _scalar_params(params)

    def test_empty_sub_queries_short_circuits_without_query(self):
        conn, cur = _mock_conn()
        result = search_knowledge_base(conn=conn, sub_queries=[], user=None)
        assert result.candidates == []
        cur.execute.assert_not_called()
