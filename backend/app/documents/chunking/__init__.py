"""Chunking sub-package for the document ingestion pipeline.

Exports StructuralChunker which preserves document structure (tables as
single chunks, headings as chunk boundaries, etc.).
"""

from app.documents.chunking.structural_chunker import Chunk, StructuralChunker

__all__ = ["StructuralChunker", "Chunk"]
