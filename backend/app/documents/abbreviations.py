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


def _initials(phrase: str) -> tuple[str, str]:
    """Initials of ``phrase``, with and without connectives.

    Hyphens and slashes split words too, so "Loan-to-Value" contributes
    l, t, v rather than a single "l".
    """
    tokens = [t for t in re.split(r"[\s\-/]+", phrase) if t]
    with_connectives = "".join(t[0] for t in tokens).lower()
    without_connectives = "".join(
        t[0] for t in tokens if t.lower() not in _CONNECTIVES
    ).lower()
    return with_connectives, without_connectives


def _trim_to_acronym(canonical: str, alias: str) -> str | None:
    """Shortest trailing span of ``canonical`` whose initials spell ``alias``.

    The "Full Term (ACR)" pattern captures up to ten preceding title-case
    words, which over-captures badly on headings: the document title
    "Down Payment and Loan-to-Value (LTV) Requirements" yielded the alias
    LTV -> "down payment and loan-to-value". Every later query mentioning
    LTV then had that whole phrase appended to its search text, dragging
    retrieval toward that one document and injecting an unrelated concept
    ("down payment") -- verified live: "What is the maximum LTV for an
    investment property?" returned the combined-LTV paragraph from the
    over-captured document with high confidence while the table holding
    the actual answer fell out of the top three entirely.

    An acronym's expansion is initial-consistent by definition, so leading
    words are dropped until the initials line up: the same title then
    yields the correct LTV -> "loan-to-value". Returns None when no span
    matches, so a bogus alias is never stored -- a wrong expansion
    silently corrupts every query containing that acronym, which is worse
    than having no expansion at all (domain_terms.py already covers the
    common industry acronyms).
    """
    words = canonical.split()
    for start in range(len(words)):
        candidate = " ".join(words[start:])
        if alias in _initials(candidate):
            return candidate
    return None


def _add(pairs: list[tuple[str, str]], seen: set[str], alias: str, canonical: str) -> None:
    alias = alias.strip().lower()
    canonical = _clean_canonical_phrase(canonical)
    if len(alias) < 2 or len(canonical) < 3:
        return
    trimmed = _trim_to_acronym(canonical, alias)
    if trimmed is None:
        return
    canonical = trimmed
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
