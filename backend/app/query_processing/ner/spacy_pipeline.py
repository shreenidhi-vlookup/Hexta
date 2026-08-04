"""spaCy NLP pipeline for query-time entity extraction.

Uses spaCy with NER disabled (GLiNER handles entity extraction).
Provides segmentation, POS tagging, and parsing for query processing.
"""

from __future__ import annotations

import logging
from typing import Iterator

logger = logging.getLogger(__name__)

try:
    import spacy

    HAS_SPACY = True
except ImportError:
    HAS_SPACY = False
    logger.warning("spaCy not installed; NLP pipeline disabled")


class SpacyPipeline:
    """Lightweight spaCy pipeline for query processing.

    NER is disabled — GLiNER owns entity extraction at query time.
    """

    def __init__(self, model_name: str = "en_core_web_sm") -> None:
        if not HAS_SPACY:
            raise RuntimeError("spaCy is required for the NLP pipeline")
        self._nlp = spacy.load(model_name, disable=["ner"])

    def process(self, text: str) -> Iterator[dict]:
        """Yield token-level annotations for a text string."""
        doc = self._nlp(text)
        for token in doc:
            yield {
                "text": token.text,
                "lemma": token.lemma_,
                "pos": token.pos_,
                "tag": token.tag_,
                "dep": token.dep_,
                "is_stop": token.is_stop,
            }

    def segment(self, text: str) -> list[str]:
        """Split text into sentences using spaCy's sentence boundary detection."""
        doc = self._nlp(text)
        return [sent.text for sent in doc.sents]

    def lemmatize(self, text: str) -> list[str]:
        """Return lemmatized tokens for a text string."""
        doc = self._nlp(text)
        return [token.lemma_ for token in doc if not token.is_stop and token.is_alpha]