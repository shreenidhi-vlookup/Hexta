"""Unit tests for query-time doc-derived alias resolution.

Uses a fake connection/cursor — no live Postgres required.
"""

from __future__ import annotations

from app.query_processing.alias_resolver import resolve_doc_aliases


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)


class TestAliasResolver:
    def test_resolves_known_alias(self):
        conn = _FakeConn([{"canonical": "Subject Access Request"}])
        assert resolve_doc_aliases(conn, "what is sar") == ["Subject Access Request"]

    def test_no_alias_no_rows(self):
        conn = _FakeConn([])
        assert resolve_doc_aliases(conn, "what is equity release") == []

    def test_empty_text(self):
        assert resolve_doc_aliases(_FakeConn([("x",)]), "") == []

    def test_alias_already_in_text_skipped(self):
        conn = _FakeConn([{"canonical": "equity release"}])
        assert resolve_doc_aliases(conn, "what is equity release") == []
