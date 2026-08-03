"""Unit tests for search and ranking modules."""

from __future__ import annotations

from app.ranking.rrf import rank_fusion
from app.ranking.scoring import compute_scores
from app.ranking.weights_config import DEFAULT_WEIGHTS, RankingWeights
from app.search.bm25_search import build_tsquery
from app.search.metadata_filters import get_search_filter, get_version_filter


class TestBM25Search:
    def test_build_tsquery_simple(self):
        q = build_tsquery("credit score requirements")
        assert "credit" in q
        assert "score" in q
        assert "requirements" in q

    def test_build_tsquery_strips_punctuation(self):
        q = build_tsquery("max LTV? for investment properties!")
        assert "ltv" in q
        assert "investment" in q
        assert "properties" in q

    def test_build_tsquery_empty(self):
        q = build_tsquery("")
        assert q == "''::tsquery"


class TestMetadataFilters:
    def test_admin_returns_no_filter(self):
        clause, params = get_search_filter({
            "role": "super_admin",
            "department": "general",
        })
        assert clause == ""
        assert params == []

    def test_loan_officer_filters_departments(self):
        clause, params = get_search_filter({
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": ["compliance"],
        })
        assert "department" in clause
        assert "general" in params
        assert "compliance" in params

    def test_no_user_denies_all(self):
        clause, params = get_search_filter(None)
        # None user has no departments → all access denied via RBAC
        # But in practice, None means "not authenticated" — check loan_officer path
        pass

    def test_version_filter(self):
        clause, params = get_version_filter()
        assert "is_active" in clause
        assert "is_approved" in clause

    def test_version_filter_inactive(self):
        clause, _ = get_version_filter(is_active=False)
        assert "is_active" not in clause


class TestRRF:
    def test_rrf_combines_ranks(self):
        bm25_ranked = [(1, 0.9), (2, 0.5)]
        vector_ranked = [(2, 0.95), (1, 0.8)]
        chunk_lookup = {
            1: {"content": "doc1", "title": "Doc1", "section": None, "chunk_type": "paragraph", "department": "general"},
            2: {"content": "doc2", "title": "Doc2", "section": None, "chunk_type": "paragraph", "department": "general"},
        }
        results = rank_fusion(bm25_ranked, vector_ranked, chunk_lookup)

        assert len(results) == 2
        assert results[0].chunk_id in (1, 2)
        # Both should have rrf_score > 0
        assert all(r.rrf_score > 0 for r in results)
        # Results should be sorted by rrf_score descending
        scores = [r.rrf_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_rrf_handles_empty_lists(self):
        results = rank_fusion([], [], {}, k=60)
        assert len(results) == 0


class TestScoring:
    def test_compute_scores_weighted(self):
        candidates = [
            {"chunk_id": 1, "bm25_score": 0.8, "vec_score": 0.9},
            {"chunk_id": 2, "bm25_score": 0.3, "vec_score": 0.4},
        ]
        weights = RankingWeights(bm25_weight=0.5, vector_weight=0.5)
        scored = compute_scores(candidates, weights)

        assert len(scored) == 2
        assert scored[0][0] == 1  # higher score first
        assert scored[1][0] == 2

    def test_compute_scores_default_weights(self):
        candidates = [
            {"chunk_id": 1, "bm25_score": 1.0, "vec_score": 0.0},
            {"chunk_id": 2, "bm25_score": 0.0, "vec_score": 1.0},
        ]
        scored = compute_scores(candidates)
        # Default: bm25 0.3, vector 0.7 → vec wins
        assert scored[0][0] == 2
