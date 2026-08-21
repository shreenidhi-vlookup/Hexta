"""Query expansion via the synonym/acronym dictionary.

Expands acronyms and aliases into their canonical phrase so that both
BM25 (exact-term matching) and the embedding model (dense semantics) see
richer text. The original terms are kept — expansion *adds* signal, it
never replaces the user's words.

Phase 5 Multi-Query: ``generate_query_variants`` derives a small set of
*fully deterministic* rewrites of the query (alias-expanded form,
definition-subject form). Each variant is embedded separately by the
hybrid orchestrator and fused, so a paraphrase-shaped question still
reaches chunks phrased differently. No LLM, no generation — pure string
transforms (CLAUDE.md core philosophy).
"""

from __future__ import annotations

import re

from app.query_processing import domain_terms
from app.query_processing.entity_extraction import Entity, extract_entities

# "What is X?" / "Define X" / "What does X mean" — the definitional
# intent questions whose answer lives in a "Term: definition" chunk
# under the bare subject, not under the full interrogative sentence.
_DEFINITION_RE = re.compile(
    r"^\s*(?:what\s+(?:is|are|was|were)|define|meaning\s+of|"
    r"what\s+does\s+\S+\s+mean)\s+(.+?)\s*\??\s*$",
    re.IGNORECASE,
)

# Upper bound on emitted variants (original included). Retrieval cost is
# linear in embeddings; three covers the transform set below.
MAX_QUERY_VARIANTS = 3


def expand(text: str, entities: list[Entity]) -> str:
    """Return ``text`` with canonical phrases appended for matched terms.

    e.g. ``max ltv for investment properties`` ->
    ``max ltv for investment properties loan to value investment property``
    """
    parts = [text]
    seen: set[str] = set()
    for e in entities:
        if e.term_type in ("percentage", "amount"):
            continue
        if e.canonical in seen:
            continue
        # Don't append the canonical if the user already typed it verbatim.
        if e.canonical in text:
            seen.add(e.canonical)
            continue
        seen.add(e.canonical)
        parts.append(e.canonical)
    return " ".join(parts).strip()


def generate_query_variants(text: str) -> list[str]:
    """Deterministic query variants, original first, deduplicated.

    1. The query as-is.
    2. Alias-expanded form (canonical domain phrases appended).
    3. Definition-subject form — for "What is X?" style questions, the
       bare subject plus the word "definition", which matches the
       structural chunker's ``Term: definition`` units directly.
    """
    base = (text or "").strip()
    if not base:
        return []

    variants: list[str] = [base]
    seen = {base.casefold()}

    def _add(candidate: str | None) -> None:
        if not candidate:
            return
        key = candidate.casefold()
        if key not in seen and len(variants) < MAX_QUERY_VARIANTS:
            seen.add(key)
            variants.append(candidate)

    _add(expand(base, extract_entities(base)))

    m = _DEFINITION_RE.match(base)
    if m:
        subject = m.group(1).strip().rstrip("?").strip()
        if subject:
            _add(f"{subject} definition")

    return variants
