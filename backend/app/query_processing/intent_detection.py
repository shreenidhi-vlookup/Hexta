"""Lightweight intent detection.

Classifies a sub-query into a coarse intent bucket used for:
- the response's intent label,
- a small metadata (doc_type) boost in ranking,
- evaluation analysis.

Pure keyword matching — deterministic, zero dependencies.
"""

from __future__ import annotations

import re

from app.query_processing import comparison, domain_terms
from app.query_processing.entity_extraction import Entity

_WORD_RE = re.compile(r"[a-z]+")

# Metrics whose min/max wording is a qualifying threshold ("minimum credit
# score", "minimum down payment") rather than a numeric cap the borrower is
# optimizing ("maximum LTV", "max loan amount"). Without this, "minimum"/
# "maximum" being in INTENT_KEYWORDS["limits"] makes every such question
# match "limits" before the "requirements" branch is ever reached, since
# "limits" has higher precedence.
_REQUIREMENT_THRESHOLD_METRICS = {"credit score", "down payment"}


def detect_intent(text: str, entities: list[Entity]) -> str:
    """Return the dominant intent for a sub-query.

    Precedence: costs > limits > documents > eligibility > requirements
    > process > definition > general.
    """
    words = set(_WORD_RE.findall(text))
    lower = text.lower()

    if any(e.term_type == "metric" and e.canonical in ("annual percentage rate", "private mortgage insurance", "mortgage insurance premium") for e in entities):
        if words & domain_terms.INTENT_KEYWORDS["costs"]:
            return "costs"
    if "loan to value" in [e.canonical for e in entities]:
        if words & domain_terms.INTENT_KEYWORDS["limits"]:
            return "limits"
    if any(e.canonical in _REQUIREMENT_THRESHOLD_METRICS for e in entities):
        if words & domain_terms.INTENT_KEYWORDS["limits"]:
            return "requirements"

    # A comparison question ("FHA vs VA", "difference between X and Y") is
    # asking what each thing IS, not whether the asker is eligible for one —
    # route it to "definition" at that precedence slot (comparison.py
    # already has the tested pattern set for recognizing these; reuse it
    # instead of duplicating regexes here).
    is_comparison_q = comparison.is_comparison(text)

    for intent in ("costs", "limits", "documents", "eligibility", "requirements", "process", "definition"):
        kws = domain_terms.INTENT_KEYWORDS[intent]
        matched = any(kw in lower for kw in kws)
        if intent == "definition" and is_comparison_q:
            matched = True
        if matched:
            return intent

    # Unreachable for comparison questions: the loop above always resolves
    # them at the "definition" slot before falling through here.
    if any(e.term_type == "document" for e in entities):
        return "documents"
    if any(e.term_type == "metric" for e in entities):
        return "requirements"
    if any(e.term_type == "property" or e.term_type == "lender" for e in entities):
        return "eligibility"
    return "general"
