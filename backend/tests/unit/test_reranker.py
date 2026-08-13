"""Unit tests for the cross-encoder reranker wrapper.

These exercise the wrapper's contract with a stubbed model, so they run
without downloading the ONNX weights.
"""

from __future__ import annotations

import pytest

from app.ranking import reranker


@pytest.fixture(autouse=True)
def _clear_model_cache():
    """The model is process-cached; drop it around each test."""
    reranker._get_reranker.cache_clear()
    yield
    reranker._get_reranker.cache_clear()


class _StubModel:
    def __init__(self, scores, calls=None):
        self._scores = scores
        self._calls = calls if calls is not None else []

    def rerank(self, query, documents):
        self._calls.append((query, list(documents)))
        return list(self._scores)


@pytest.fixture
def CANDIDATES():
    """Fresh dicts per test -- rerank() attaches rerank_score in place, so
    a shared module-level list would leak state between tests."""
    return [
        {"chunk_id": 1, "content": "HVAC filters should be replaced every 1-3 months."},
        {"chunk_id": 2, "content": "FHA requires 3.5% down with a 580 credit score."},
        {"chunk_id": 3, "content": "Title insurance protects against defects in title."},
    ]


class TestRerankOrdering:
    def test_reorders_by_score_descending(self, monkeypatch, CANDIDATES):
        monkeypatch.setattr(reranker.settings, "rerank_enabled", True)
        monkeypatch.setattr(
            reranker, "_get_reranker", lambda: _StubModel([-5.0, 9.0, -1.0])
        )
        out = reranker.rerank("fha down payment", CANDIDATES, top_k=3)
        assert [c["chunk_id"] for c in out] == [2, 3, 1]

    def test_scores_are_attached_by_position(self, monkeypatch, CANDIDATES):
        """A score must land on the document it was computed for."""
        monkeypatch.setattr(reranker.settings, "rerank_enabled", True)
        monkeypatch.setattr(
            reranker, "_get_reranker", lambda: _StubModel([-5.0, 9.0, -1.0])
        )
        out = reranker.rerank("fha down payment", CANDIDATES, top_k=3)
        by_id = {c["chunk_id"]: c["rerank_score"] for c in out}
        assert by_id == {1: -5.0, 2: 9.0, 3: -1.0}

    def test_only_top_k_are_scored(self, monkeypatch, CANDIDATES):
        """Cost is linear in candidates; the budget depends on this cap."""
        calls: list = []
        monkeypatch.setattr(reranker.settings, "rerank_enabled", True)
        monkeypatch.setattr(
            reranker, "_get_reranker", lambda: _StubModel([1.0, 2.0], calls)
        )
        out = reranker.rerank("q", CANDIDATES, top_k=2)
        assert len(out) == 2
        assert len(calls[0][1]) == 2


class TestRerankFallbacks:
    def test_disabled_returns_input_order(self, monkeypatch, CANDIDATES):
        monkeypatch.setattr(reranker.settings, "rerank_enabled", False)
        out = reranker.rerank("q", CANDIDATES, top_k=3)
        assert [c["chunk_id"] for c in out] == [1, 2, 3]

    def test_model_failure_keeps_rrf_order(self, monkeypatch, CANDIDATES):
        """A reranker problem must degrade ranking, never fail the search."""
        monkeypatch.setattr(reranker.settings, "rerank_enabled", True)

        def _boom():
            raise RuntimeError("onnx session failed")

        monkeypatch.setattr(reranker, "_get_reranker", _boom)
        out = reranker.rerank("q", CANDIDATES, top_k=3)
        assert [c["chunk_id"] for c in out] == [1, 2, 3]

    def test_score_count_mismatch_keeps_rrf_order(self, monkeypatch, CANDIDATES):
        """Rather than zip-truncating and attaching a score to the wrong
        chunk, a length mismatch falls back to the incoming order."""
        monkeypatch.setattr(reranker.settings, "rerank_enabled", True)
        monkeypatch.setattr(reranker, "_get_reranker", lambda: _StubModel([1.0]))
        out = reranker.rerank("q", CANDIDATES, top_k=3)
        assert [c["chunk_id"] for c in out] == [1, 2, 3]
        assert all("rerank_score" not in c for c in out)

    def test_empty_candidates(self, monkeypatch):
        monkeypatch.setattr(reranker.settings, "rerank_enabled", True)
        assert reranker.rerank("q", [], top_k=3) == []


class TestModelCaching:
    def test_model_is_constructed_once(self, monkeypatch, CANDIDATES):
        """The previous implementation built its scorer inside rerank(),
        reloading the model on every request -- which cannot fit any
        per-query latency budget."""
        import sys
        import types

        constructions = {"n": 0}

        class _FakeEncoder:
            def __init__(self, *args, **kwargs):
                constructions["n"] += 1

            def rerank(self, query, documents):
                return [1.0] * len(list(documents))

        module = types.ModuleType("fastembed.rerank.cross_encoder")
        module.TextCrossEncoder = _FakeEncoder
        monkeypatch.setitem(sys.modules, "fastembed.rerank.cross_encoder", module)
        monkeypatch.setattr(reranker.settings, "rerank_enabled", True)

        for _ in range(3):
            reranker.rerank("q", CANDIDATES, top_k=3)

        assert constructions["n"] == 1
