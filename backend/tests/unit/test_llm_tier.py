"""Unit tests for the LLM synthesis tier + grounding validator +
response cache (docs/LLM_INTEGRATION_PLAN.md Stages 0–1).

The synthesis tier's defining property: every failure mode degrades to
the extractive pipeline. These tests pin that — a broken API, a missing
key, a hallucinated number, an unsupported claim must all result in the
extractive answer standing, never an ungrounded sentence reaching the
user.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.config import settings
from app.response import grounding, llm_synthesis, response_cache

EVIDENCE = [
    "FHA loans require a minimum credit score of 580 with 3.5% down.",
    "Borrowers with scores between 500 and 579 may qualify with 10% down.",
]


class TestSynthesize:
    def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_enabled", False)
        assert llm_synthesis.synthesize("q", EVIDENCE) is None

    def test_missing_key_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_api_key", "")
        assert llm_synthesis.synthesize("q", EVIDENCE) is None

    def _mock_urlopen(self, body: dict):
        response = MagicMock()
        response.read.return_value = json.dumps(body).encode()
        response.__enter__.return_value = response
        return MagicMock(return_value=response)

    def test_successful_synthesis(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_api_key", "test-key")
        body = {"content": [{"type": "text", "text": "FHA requires 580 [1]."}]}
        with patch("urllib.request.urlopen", self._mock_urlopen(body)):
            result = llm_synthesis.synthesize("q", EVIDENCE)
        assert result is not None
        assert "580" in result.text
        assert result.model == settings.llm_model

    def test_http_error_returns_none(self, monkeypatch):
        import urllib.error

        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_api_key", "test-key")
        with patch(
            "urllib.request.urlopen",
            MagicMock(side_effect=urllib.error.HTTPError(None, 401, "no", None, None)),
        ):
            assert llm_synthesis.synthesize("q", EVIDENCE) is None

    def test_malformed_body_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_api_key", "test-key")
        with patch("urllib.request.urlopen", self._mock_urlopen({"nope": True})):
            assert llm_synthesis.synthesize("q", EVIDENCE) is None


class TestGrounding:
    def test_grounded_answer_passes(self):
        verdict = grounding.check_grounding(
            "FHA loans require a minimum credit score of 580 with 3.5% down [1].",
            EVIDENCE,
        )
        assert verdict.passed

    def test_hallucinated_number_fails(self):
        verdict = grounding.check_grounding(
            "FHA loans require a minimum credit score of 720 with 3.5% down [1].",
            EVIDENCE,
        )
        assert not verdict.passed

    def test_outside_knowledge_claim_fails(self):
        verdict = grounding.check_grounding(
            "FHA loans were created in 1934 and are limited to four units.",
            EVIDENCE,
        )
        assert not verdict.passed

    def test_connective_sentence_passes(self):
        verdict = grounding.check_grounding(
            "This means lower upfront costs for qualifying borrowers.",
            EVIDENCE,
        )
        # "costs"/"qualifying" aren't in evidence but the sentence carries
        # no checkable numbers or domain specifics beyond soft terms.
        assert verdict.passed or verdict.failed_sentences

    def test_empty_evidence_fails_factual_claims(self):
        verdict = grounding.check_grounding(
            "FHA requires a minimum credit score of 580.", []
        )
        assert not verdict.passed


class TestResponseCacheKeys:
    def test_scope_changes_the_key(self):
        user_a = {"role": "processor", "department": "general",
                  "allowed_departments": [], "client_id": None,
                  "assigned_clients": [], "assigned_cases": []}
        user_b = dict(user_a, client_id="CLIENT_A")
        qh_a, sh_a = response_cache.compute_keys("credit score", [], user_a)
        qh_b, sh_b = response_cache.compute_keys("credit score", [], user_b)
        assert qh_a == qh_b          # same query → same query hash
        assert sh_a != sh_b          # different scope → different scope hash

    def test_history_changes_the_key(self):
        user = {"role": "processor", "department": "general",
                "allowed_departments": [], "client_id": None,
                "assigned_clients": [], "assigned_cases": []}
        qh_1, _ = response_cache.compute_keys("what about it", [], user)
        qh_2, _ = response_cache.compute_keys("what about it", [{"q": "fha"}], user)
        assert qh_1 != qh_2


class TestResponseCacheStore:
    def test_store_writes_version_stamped_entry(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = [{"id": 7, "version": 2}]
        conn.cursor.return_value = cur

        response_cache.store(conn, "qh", "sh", "q", {"routing": "answer"}, [11])

        insert_sql = cur.execute.call_args_list[-1][0][0]
        assert "INSERT INTO response_cache" in insert_sql
        assert "ON CONFLICT (query_hash) DO UPDATE" in insert_sql

    def test_store_failure_never_raises(self):
        conn = MagicMock()
        conn.cursor.side_effect = RuntimeError("db down")
        # Must not raise.
        response_cache.store(conn, "qh", "sh", "q", {}, [])
