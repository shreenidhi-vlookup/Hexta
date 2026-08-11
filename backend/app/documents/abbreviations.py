"""Harvest acronym definitions from document text.

Recognises the two most common presentation styles:

- ``Full Term (ACR)``        e.g. ``Subject Access Request (SAR)``
- ``ACR: Full Term``         e.g. ``SAR: Subject Access Request``
- ``ACR — Full Term``        (em/en dash separator)

Captured phrases are trimmed to a plausible noun phrase (title-case words
joined by connectives like ``to``/``of``/``the``), so trailing prose such
as ``... is a legal right`` is dropped. Aliases and canonicals are stored
lowercased to match the lowercased query text.
"""

from __future__ import annotations

import re

# "Full Term (ACR)" — canonical words may be title-case or short
# connectives (to, of, the, and ...) so phrases like "Loan to Value (LTV)"
# are captured whole.
_FULL_FIRST_RE = re.compile(
    r"((?:[A-Z][a-zA-Z']+(?:\s|/|-)*|[a-z]{2,3}(?:\s|/|-)*){1,10})"
    r"\s*\(([A-Z][A-Z0-9]{1,10})\)"
)

# "ACR: Full Term" / "ACR — Full Term" — capture text after the separator
# up to the first sentence terminator, then trim to a noun phrase.
_ACRONYM_FIRST_RE = re.compile(
    r"\b([A-Z][A-Z0-9]{1,10})\b\s*[-—:]\s*([A-Za-z][A-Za-z ,&'/-]{1,160}?)"
    r"(?=[.!?;]|\n|$)"
)

_CONNECTIVES = frozenset(
    ("to", "of", "the", "for", "and", "a", "an", "in", "on", "with",
     "at", "by", "from", "or", "into", "over", "between")
)


def _clean_canonical_phrase(text: str) -> str:
    """Keep a leading noun phrase: title-case words + connectives."""
    words = re.findall(r"[A-Za-z0-9&'-]+", text)
    out: list[str] = []
    for word in words:
        if word[:1].isupper() or word.lower() in _CONNECTIVES:
            out.append(word)
        else:
            break
    while out and out[0].lower() in _CONNECTIVES:
        out.pop(0)
    while out and out[-1].lower() in _CONNECTIVES:
        out.pop()
    return " ".join(out).strip().lower()


def _add(pairs: list[tuple[str, str]], seen: set[str], alias: str, canonical: str) -> None:
    alias = alias.strip().lower()
    canonical = _clean_canonical_phrase(canonical)
    if len(alias) < 2 or len(canonical) < 3:
        return
    if alias == canonical or alias in canonical:
        return
    if alias in seen:
        return
    seen.add(alias)
    pairs.append((alias, canonical))


def harvest_abbreviations(text: str) -> list[tuple[str, str]]:
    """Return ``(alias, canonical)`` pairs found in ``text``."""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    for match in _FULL_FIRST_RE.finditer(text or ""):
        _add(pairs, seen, match.group(2), match.group(1))

    for match in _ACRONYM_FIRST_RE.finditer(text or ""):
        _add(pairs, seen, match.group(1), match.group(2))

    return pairs
