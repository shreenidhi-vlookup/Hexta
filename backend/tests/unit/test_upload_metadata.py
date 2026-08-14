"""Unit tests for the upload category sidecar.

The upload endpoint may not ingest (CLAUDE.md rule 5), so the admin's
category choice has to reach the batch ingester some other way. A JSON
file named after the stored document carries it across that process
boundary.
"""

from __future__ import annotations

from pathlib import Path

from app.documents import upload_metadata as um


class TestSidecarPath:
    def test_path_is_derived_from_the_document_name(self, tmp_path: Path):
        doc = tmp_path / "abc123_report.pdf"
        assert um.sidecar_path(doc).name == "abc123_report.pdf.meta.json"

    def test_sidecar_sits_beside_the_document(self, tmp_path: Path):
        doc = tmp_path / "abc123_report.pdf"
        assert um.sidecar_path(doc).parent == tmp_path


class TestWrite:
    def test_writes_both_fields(self, tmp_path: Path):
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        um.write_sidecar(doc, doc_type="glossary", department="underwriting")
        assert um.read_sidecar(doc) == {
            "doc_type": "glossary",
            "department": "underwriting",
        }

    def test_omits_absent_fields(self, tmp_path: Path):
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        um.write_sidecar(doc, doc_type=None, department="compliance")
        assert um.read_sidecar(doc) == {"department": "compliance"}

    def test_writes_nothing_when_both_absent(self, tmp_path: Path):
        """No choice made -> no file, so ingestion detects as it always did."""
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        assert um.write_sidecar(doc, doc_type=None, department=None) is None
        assert not um.sidecar_path(doc).exists()


class TestRead:
    def test_missing_sidecar_reads_as_empty(self, tmp_path: Path):
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        assert um.read_sidecar(doc) == {}

    def test_corrupt_sidecar_reads_as_empty(self, tmp_path: Path):
        """A malformed sidecar must degrade to detection, never crash a
        batch run and strand the document in pending/ forever."""
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        um.sidecar_path(doc).write_text("{not json")
        assert um.read_sidecar(doc) == {}

    def test_non_object_sidecar_reads_as_empty(self, tmp_path: Path):
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        um.sidecar_path(doc).write_text('["glossary"]')
        assert um.read_sidecar(doc) == {}

    def test_unknown_keys_are_dropped(self, tmp_path: Path):
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        um.sidecar_path(doc).write_text('{"doc_type": "policy", "evil": "x"}')
        assert um.read_sidecar(doc) == {"doc_type": "policy"}


class TestMove:
    def test_sidecar_follows_the_document(self, tmp_path: Path):
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        um.write_sidecar(doc, "policy", "general")
        dest = tmp_path / "processed"
        dest.mkdir()
        um.move_sidecar(doc, dest)
        assert (dest / "d.txt.meta.json").exists()
        assert not um.sidecar_path(doc).exists()

    def test_move_is_a_noop_without_a_sidecar(self, tmp_path: Path):
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        dest = tmp_path / "processed"
        dest.mkdir()
        um.move_sidecar(doc, dest)  # must not raise
