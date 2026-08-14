"""Unit tests for index_document's INSERT contract.

Adding a column to the documents INSERT means adding a placeholder and a
parameter in matching positions. Get that wrong and nothing fails until a
real ingestion run, which happens in a detached subprocess whose failure
surfaces only as a document that never appears.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.documents.chunking.structural_chunker import Chunk
from app.documents.indexing import index_document


def _mock_conn(document_id: int = 1):
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = {"id": document_id}
    cur.rowcount = 1
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


def _chunk() -> Chunk:
    return Chunk(
        content="Amortization: paying a loan off over time.",
        section="Core Terms",
        chunk_type="definition",
        page_number=None,
    )


def _document_insert_call(cur):
    """The first execute() whose SQL inserts into documents."""
    for call in cur.execute.call_args_list:
        sql = call[0][0]
        if "INSERT INTO documents" in sql:
            return call
    raise AssertionError("no INSERT INTO documents was issued")


class TestDocumentInsert:
    def test_placeholders_match_parameters(self):
        conn, cur = _mock_conn()
        index_document(
            conn=conn, doc_title="T", doc_type="policy", department="general",
            source_path="p.txt", chunks=[_chunk()], uploaded_by=7,
        )
        sql, params = _document_insert_call(cur)[0]
        assert sql.count("%s") == len(params)

    def test_uploaded_by_is_persisted(self):
        conn, cur = _mock_conn()
        index_document(
            conn=conn, doc_title="T", doc_type="policy", department="general",
            source_path="p.txt", chunks=[_chunk()], uploaded_by=7,
        )
        _sql, params = _document_insert_call(cur)[0]
        assert 7 in params

    def test_uploaded_by_is_optional(self):
        """Batch runs that bypass the upload endpoint have no uploader."""
        conn, cur = _mock_conn()
        index_document(
            conn=conn, doc_title="T", doc_type="policy", department="general",
            source_path="p.txt", chunks=[_chunk()],
        )
        sql, params = _document_insert_call(cur)[0]
        assert sql.count("%s") == len(params)

    def test_documents_are_inserted_unapproved(self):
        """The approval gate: an upload is not retrievable until an admin
        approves it, and that starts here."""
        conn, cur = _mock_conn()
        index_document(
            conn=conn, doc_title="T", doc_type="policy", department="general",
            source_path="p.txt", chunks=[_chunk()], uploaded_by=7,
        )
        sql, _params = _document_insert_call(cur)[0]
        assert "false" in sql.lower()
