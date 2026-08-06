"""Query-time resolution of doc-derived aliases (acronyms).

Uses the ``term_aliases`` table populated during ingestion. Given a
sub-query, looks up 1..N word ngrams and returns canonical expansions
for any alias present. This lets "what is SAR?" resolve whenever the
knowledge base contains "Subject Access Request (SAR)".

Requires a DB connection (it is NOT part of the pure query pipeline);
callers pass the alias-aware expansion into the search step.
"""

from __future__ import annotations

import logging
import re

from app.config import settings

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z]+[0-9]*")


def resolve_doc_aliases(conn, text: str) -> list[str]:
    """Return canonical expansions for aliases contained in ``text``.

    Best-effort: returns [] on any DB error so retrieval never breaks.
    """
    words = _WORD_RE.findall((text or "").lower())
    if not words:
        return []

    max_n = min(settings.max_alias_ngram, len(words))
    ngrams: set[str] = set()
    for n in range(1, max_n + 1):
        for i in range(len(words) - n + 1):
            ngrams.add(" ".join(words[i : i + n]))
    if not ngrams:
        return []

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT canonical FROM term_aliases "
                "WHERE lower(alias) = ANY(%s) "
                "ORDER BY length(canonical) DESC LIMIT 20",
                (list(ngrams),),
            )
            rows = cur.fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Alias resolution failed: %s", exc)
        return []

    canonicals = [row["canonical"] for row in rows if row and row.get("canonical")]
    out: list[str] = []
    for canonical in canonicals:
        if canonical and canonical not in text and canonical not in out:
            out.append(canonical)
    return out
