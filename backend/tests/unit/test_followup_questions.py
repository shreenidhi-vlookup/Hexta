"""Unit tests for topic-based follow-up question suggestions."""

from __future__ import annotations

from app.response.followup_questions import suggest_followups


class FakeCursor:
    def __init__(self, result):
        self.result = result

    def execute(self, sql, params):
        pass

    def fetchone(self):
        return (self.result,)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConn:
    def __init__(self, answerable=True):
        self.answerable = answerable

    def cursor(self):
        return FakeCursor(self.answerable)


class TestTopicFollowups:
    def test_lifetime_mortgage_topic(self):
        fq = suggest_followups(FakeConn(), ["what is a lifetime mortgage"])
        assert fq
        assert "lifetime mortgage" in " ".join(fq)

    def test_equity_release_topic(self):
        fq = suggest_followups(FakeConn(), ["what is equity release"])
        assert "equity release" in " ".join(fq)

    def test_never_echoes_user_sub_questions(self):
        user_q = "what is equity release"
        fq = suggest_followups(FakeConn(), [user_q])
        for q in fq:
            assert q.lower() != user_q

    def test_bridging_finance_topic(self):
        fq = suggest_followups(FakeConn(), ["how does bridging finance work"])
        assert "bridging" in " ".join(fq)

    def test_no_duplicates_and_capped_at_three(self):
        fq = suggest_followups(FakeConn(), ["lifetime mortgage equity release"])
        assert len(fq) <= 3
        assert len(fq) == len(set(fq))

    def test_generic_fallback_when_no_topic(self):
        fq = suggest_followups(FakeConn(), ["what is the weather like"])
        assert len(fq) == 3
        assert any("documents" in q for q in fq)
        assert any("How long" in q for q in fq)

    def test_verification_failure_falls_back(self):
        fq = suggest_followups(FakeConn(answerable=False), ["lifetime mortgage"])
        assert len(fq) == 3

    def test_empty_sub_queries(self):
        fq = suggest_followups(FakeConn(), [])
        assert fq
