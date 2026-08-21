"""Unit tests for Phase 5 Multi-Query + Self-RAG subset.

Multi-Query: generate_query_variants must emit deterministic rewrites
(original first, deduplicated, capped) and the orchestrator must embed
every variant — visible as one similarity term per vector in the SQL.

Self-RAG subset: _build_block retries once with an alternate variant only
when the cross-encoder affirmatively vetoed the evidence, and keeps the
retry only when its top rerank score is better AND answerable.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.query_processing.query_expansion import (
    MAX_QUERY_VARIANTS,
    generate_query_variants,
)
from app.search.hybrid_orchestrator import search_knowledge_base


def _mock_conn(rows=None):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = rows or []
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    conn.cursor.return_value = cur
    return conn, cur


class TestGenerateQueryVariants:
    def test_original_is_always_first(self):
        variants = generate_query_variants("credit score requirements")
        assert variants[0] == "credit score requirements"

    def test_empty_input_yields_no_variants(self):
        assert generate_query_variants("") == []
        assert generate_query_variants(None) == []

    def test_definitional_question_gets_subject_variant(self):
        variants = generate_query_variants("What is underwriting?")
        assert any(v.startswith("underwriting") for v in variants[1:])

    def test_define_form_gets_subject_variant(self):
        variants = generate_query_variants("define amortization")
        assert any("amortization definition" in v.lower() for v in variants)

    def test_non_definitional_question_has_no_subject_variant(self):
        variants = generate_query_variants(
            "How does a loan gradually get paid off?"
        )
        assert not any("definition" in v.lower() for v in variants)

    def test_variants_are_deduplicated_and_capped(self):
        variants = generate_query_variants("what is fha?")
        assert len(variants) == len({v.casefold() for v in variants})
        assert len(variants) <= MAX_QUERY_VARIANTS


class TestMultiVectorFusion:
    def test_one_similarity_term_per_variant(self):
        conn, cur = _mock_conn()
        sub = "what is fha?"
        search_knowledge_base(conn=conn, sub_queries=[sub], user=None)
        query, _params = cur.execute.call_args[0]
        # Each variant contributes exactly 3 <=> uses: WHERE admission,
        # vec_score GREATEST, and the vec_rank window.
        n_variants = len(generate_query_variants(sub))
        assert n_variants >= 2
        assert query.count("<=>") == 3 * n_variants

    def test_placeholder_count_matches_with_multiple_variants(self):
        conn, cur = _mock_conn()
        search_knowledge_base(
            conn=conn,
            sub_queries=["define amortization"],
            user={"role": "client", "department": "general", "client_id": "C1"},
        )
        query, params = cur.execute.call_args[0]
        assert query.count("%s") == len(params)

    def test_bm25_gate_still_not_unconditional(self):
        """Regression guard: multi-vector admission must stay inside the
        OR with BM25, never a top-level AND-term."""
        conn, cur = _mock_conn()
        search_knowledge_base(conn=conn, sub_queries=["what is equity?"], user=None)
        query, _ = cur.execute.call_args[0]
        where_clause = query.split("WHERE", 1)[1].split("ORDER BY", 1)[0]
        assert "OR (1 - (c.embedding <=> %s)) >= %s" in where_clause


class TestAnswerabilityRetry:
    def _patch_attempt(self, results):
        """Patch _run_attempt to return queued results in order."""
        calls = {"n": 0}

        def fake_attempt(_conn, question, search_text, user):
            idx = min(calls["n"], len(results) - 1)
            calls["n"] += 1
            block, ids, score = results[idx]
            return block, ids, score

        return patch(
            "app.api.v1.search._run_attempt", side_effect=fake_attempt
        ), calls

    def _block(self, routing="no_answer"):
        from app.api.v1.search import AnswerBlock

        return AnswerBlock(
            question="q", title="t", answer_phrase="a",
            excerpts=[], confidence=10.0, routing=routing,
        )

    def test_retry_fires_on_veto_and_keeps_better_alternate(self):
        from app.api.v1.search import _build_block

        with patch("app.api.v1.search.settings") as mock_settings:
            mock_settings.rerank_enabled = True
            with patch(
                "app.api.v1.search.generate_query_variants",
                return_value=["orig", "alt"],
            ):
                p, _calls = self._patch_attempt([
                    (self._block(), [1], -9.0),   # vetoed
                    (self._block("answer"), [2], 5.0),  # answerable retry
                ])
                with p:
                    block, ids = _build_block(None, "q", "orig", user={})
        assert block.routing == "answer"
        assert ids == [2]

    def test_no_retry_when_reranking_disabled(self):
        from app.api.v1.search import _build_block

        with patch("app.api.v1.search.settings") as mock_settings:
            mock_settings.rerank_enabled = False
            with patch(
                "app.api.v1.search.generate_query_variants",
                return_value=["orig", "alt"],
            ) as gv:
                p, _calls = self._patch_attempt([
                    (self._block(), [1], None),
                ])
                with p:
                    block, _ids = _build_block(None, "q", "orig", user={})
                gv.assert_not_called()
        assert block.routing == "no_answer"

    def test_vetoed_retry_is_discarded_when_still_bad(self):
        from app.api.v1.search import _build_block

        with patch("app.api.v1.search.settings") as mock_settings:
            mock_settings.rerank_enabled = True
            with patch(
                "app.api.v1.search.generate_query_variants",
                return_value=["orig", "alt"],
            ):
                p, _calls = self._patch_attempt([
                    (self._block(), [1], -8.0),
                    (self._block(), [2], -7.0),   # still vetoed
                ])
                with p:
                    block, ids = _build_block(None, "q", "orig", user={})
        assert ids == [1]

    @pytest.mark.parametrize("variants", [["only-one"]])
    def test_no_retry_without_alternate_variant(self, variants):
        from app.api.v1.search import _build_block

        with patch("app.api.v1.search.settings") as mock_settings:
            mock_settings.rerank_enabled = True
            with patch(
                "app.api.v1.search.generate_query_variants",
                return_value=variants,
            ):
                p, calls = self._patch_attempt([
                    (self._block(), [1], -9.0),
                ])
                with p:
                    _block_out, _ids = _build_block(None, "q", "only-one", user={})
        assert calls["n"] == 1
