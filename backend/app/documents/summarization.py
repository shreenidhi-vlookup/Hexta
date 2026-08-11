"""Extractive summarization for document chunks (batch ingestion only).

This module runs exclusively inside the batch ingestion pipeline
(infra/scripts/run_ingestion.sh → ingest_batch.py). It is NEVER
called from the request-serving path, keeping the serving pipeline
100% retrieval-only with no synthesized text at query time.

Summaries are pre-computed at ingest time and stored in the
document_chunks.summary column. At query time the frontend shows
the chunk's summary (or content) verbatim — no generation happens
in the serving path.
"""

from __future__ import annotations

import logging

from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lsa import LsaSummarizer

logger = logging.getLogger(__name__)


def summarize_chunk(content: str, sentences_count: int = 2) -> str | None:
    """Produce an extractive summary of a chunk's content.

    Returns None if the content is too short to summarize or if
    summarization fails for any reason.
    """
    if not content or len(content.strip()) < 100:
        return None

    try:
        parser = PlaintextParser.from_string(content, Tokenizer("english"))
        summarizer = LsaSummarizer()
        sentences = summarizer(parser.document, sentences_count)
        summary = " ".join(str(sentence) for sentence in sentences)
        return summary.strip() if summary.strip() else None
    except Exception as exc:
        logger.warning("Summarization failed for chunk: %s", exc)
        return None