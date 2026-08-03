"""Unit tests for document ingestion modules."""

from __future__ import annotations

from app.documents.validation import validate_upload
from app.documents.chunking.structural_chunker import StructuralChunker
from app.documents.text_extraction import ExtractedText
from app.documents.metadata_extraction import extract_metadata


class TestValidation:
    def test_valid_txt_file(self):
        result = validate_upload("doc.txt", 1024)
        assert result.valid is True
        assert result.error is None

    def test_valid_pdf_file(self):
        result = validate_upload("doc.pdf", 1024 * 1024)
        assert result.valid is True

    def test_invalid_extension(self):
        result = validate_upload("doc.exe", 100)
        assert result.valid is False
        assert "not allowed" in result.error

    def test_oversized_file(self):
        result = validate_upload("doc.txt", 25 * 1024 * 1024)
        assert result.valid is False
        assert "exceeds limit" in result.error

    def test_case_insensitive_extension(self):
        result = validate_upload("DOC.PDF", 1024)
        assert result.valid is True


class TestStructuralChunker:
    def test_chunk_plain_text(self):
        extractor = ExtractedText(
            text="This is a test. " * 100,  # ~230 words
            pages=[],
            source_format="txt",
        )
        chunker = StructuralChunker(max_tokens=50)
        chunks = list(chunker.chunk(extractor))
        assert len(chunks) > 1
        assert all(c.chunk_type == "paragraph" for c in chunks)

    def test_chunk_preserves_tables(self):
        text = (
            "Some intro paragraph here.\n\n"
            "col1 col2 col3\n"
            "val1 val2 val3\n"
            "val4 val5 val6\n\n"
            "Another paragraph after the table."
        )
        extractor = ExtractedText(text=text, pages=[], source_format="txt")
        chunker = StructuralChunker(max_tokens=500)
        chunks = list(chunker.chunk(extractor))

        table_chunks = [c for c in chunks if c.chunk_type == "table"]
        assert len(table_chunks) >= 1
        assert "col1" in table_chunks[0].content

    def test_chunk_empty_text(self):
        extractor = ExtractedText(text="", pages=[], source_format="txt")
        chunker = StructuralChunker()
        chunks = list(chunker.chunk(extractor))
        assert len(chunks) == 0


class TestMetadataExtraction:
    def test_extract_title_from_content(self):
        text = "Housing Finance Guidelines\n\nSection 1: Credit scores..."
        extractor = ExtractedText(text=text, pages=[], source_format="txt")
        meta = extract_metadata(extractor, "doc.txt")
        assert meta.title is not None
        assert meta.doc_type == "policy"

    def test_extract_doc_type_from_content(self):
        text = "Underwriting guidelines for conventional loans..."
        extractor = ExtractedText(text=text, pages=[], source_format="txt")
        meta = extract_metadata(extractor, "underwriting.txt")
        assert meta.doc_type == "underwriting"
