"""GLiNER-based entity extraction for query-time NER.

Restricted to the six domain entity types (Lender, Product, Document,
Property, Number, Client) — does not expand into general NER.
Loaded lazily and only at query time to keep the API process lightweight.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator

logger = logging.getLogger(__name__)

try:
    from gliner import GLiNER

    HAS_GLINER = True
except ImportError:
    HAS_GLINER = False
    logger.warning("GLiNER not installed; query-time entity extraction disabled")


DOMAIN_ENTITY_TYPES: list[str] = [
    "Lender",
    "Product",
    "Document",
    "Property",
    "Number",
    "Client",
]


@dataclass
class QueryEntity:
    canonical: str
    term_type: str
    matched: str
    start: int
    end: int


def extract_entities(text: str) -> list[QueryEntity]:
    """Extract domain entities from a query string using GLiNER.

    Falls back to an empty list if GLiNER is not installed or fails.
    """
    if not HAS_GLINER:
        return []

    try:
        model = GLiNER("gliner-multitask-large")
        predictions = model.predict(text, labels=DOMAIN_ENTITY_TYPES)
        entities: list[QueryEntity] = []
        for pred in predictions:
            entities.append(QueryEntity(
                canonical=pred["label"],
                term_type=pred["label"].lower(),
                matched=text[pred["start"]:pred["end"]],
                start=pred["start"],
                end=pred["end"],
            ))
        return entities
    except Exception as exc:
        logger.warning("GLiNER entity extraction failed: %s", exc)
        return []