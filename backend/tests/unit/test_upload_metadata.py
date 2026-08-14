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


class TestUploadedBy:
    """The sidecar also carries who uploaded the document.

    Needed for accountability -- an admin approving a document should be
    able to see who put it forward -- and so a processor can be shown the
    status of their own uploads without being given the whole document
    list.
    """

    def test_round_trips_the_uploader(self, tmp_path: Path):
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        um.write_sidecar(doc, "policy", "general", uploaded_by=7)
        assert um.read_sidecar(doc)["uploaded_by"] == 7

    def test_uploader_alone_is_enough_to_write_a_sidecar(self, tmp_path: Path):
        """An upload with no category still needs attribution recorded."""
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        assert um.write_sidecar(doc, None, None, uploaded_by=7) is not None
        assert um.read_sidecar(doc) == {"uploaded_by": 7}

    def test_absent_uploader_is_omitted(self, tmp_path: Path):
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        um.write_sidecar(doc, "policy", None, uploaded_by=None)
        assert "uploaded_by" not in um.read_sidecar(doc)

    def test_non_integer_uploader_is_dropped(self, tmp_path: Path):
        """A hand-edited sidecar must not put a non-integer into a BIGINT
        column and fail the whole batch run."""
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        um.sidecar_path(doc).write_text('{"doc_type": "policy", "uploaded_by": "seven"}')
        parsed = um.read_sidecar(doc)
        assert parsed == {"doc_type": "policy"}

    def test_non_positive_uploader_is_dropped(self, tmp_path: Path):
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        um.sidecar_path(doc).write_text('{"uploaded_by": 0}')
        assert um.read_sidecar(doc) == {}

    def test_numeric_string_uploader_is_accepted(self, tmp_path: Path):
        """JSON round-trips through form data in places, so a digit string
        is a realistic shape and is unambiguous."""
        doc = tmp_path / "d.txt"
        doc.write_text("body")
        um.sidecar_path(doc).write_text('{"uploaded_by": "7"}')
        assert um.read_sidecar(doc) == {"uploaded_by": 7}
