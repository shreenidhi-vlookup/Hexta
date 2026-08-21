"""Embedding generation for document ingestion.

Uses FastEmbed (nomic-embed-text-v1.5-Q ONNX Int8, ~137MB) to generate
768-dimensional embeddings. Loaded lazily at first use and cached.

Nomic models are instruction-aware: inputs MUST carry the
``search_document:`` prefix here and ``search_query:`` in
``search/pgvector_search.py`` or retrieval quality degrades sharply.
Changing the embedding model invalidates every stored vector — bump the
dimension in ``db/postgres/schema.py`` and re-ingest the whole corpus.

Per CLAUDE.md rule 5: this module runs ONLY in the batch ingestion
process — never imported by app.main.py or any request handler.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Sequence

logger = logging.getLogger(__name__)

try:
    from fastembed import TextEmbedding

    _HAS_FASTEMBED = True
except ImportError:
    _HAS_FASTEMBED = False
    logger.warning("fastembed not installed; embedding generation disabled")


@lru_cache(maxsize=1)
def _get_model() -> TextEmbedding:
    """Lazily load and cache the FastEmbed model."""
    if not _HAS_FASTEMBED:
        raise RuntimeError("fastembed is not installed")
    from app.config import settings

    logger.info("Loading embedding model: %s", settings.embedding_model)
    model = TextEmbedding(
        model_name=settings.embedding_model,
        cache_dir=settings.embedding_cache_dir,
    )
    return model


def generate_embeddings(texts: Sequence[str]) -> list[list[float]]:
    """Generate embeddings for a batch of text chunks."""
    if not _HAS_FASTEMBED:
        raise RuntimeError("fastembed is not installed")

    model = _get_model()
    prefixed = [f"search_document: {t}" for t in texts]
    embeddings = list(model.embed(prefixed, batch_size=16))
    logger.info("Generated %d embeddings", len(embeddings))
    return embeddings
