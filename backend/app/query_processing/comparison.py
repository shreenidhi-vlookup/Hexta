"""Comparison-question detection and operand extraction.

Recognises requests such as:

- "what is the difference between X and Y?"
- "compare X and Y"
- "how is X different from Y?"
- "X vs Y" / "X versus Y"
- "X or Y, which is better?"

Returns the two operands. The caller searches each operand separately
and builds two answer blocks. We never invent differences — each block
only shows text retrieved from the knowledge base.

Operand extraction is intentionally greedy on the FIRST delimiter so
"difference between income and employment requirements and LTV" splits
into ("income", "employment requirements and LTV"). This is
deterministic; ambiguous inputs fall back to normal single search.
"""

from __future__ import annotations

import re

from app.query_processing import domain_terms

# Each pattern must yield exactly two operand groups. Patterns are
# matched in order, most-specific first.
_PATTERNS: list[tuple[re.Pattern, tuple[int, int]]] = []


def _add(pattern: str, left: int, right: int) -> None:
    _PATTERNS.append((re.compile(pattern, re.IGNORECASE), (left, right)))


# The "what is the" lead-in is optional: bare "difference between X and
# Y" (no question-word prefix at all) previously matched no pattern here,
# so is_comparison() returned False for it and comparison detection never
# ran -- verified live for "difference between PMI and MIP".
_add(r"^(?:what(?:'s| is| are)?\s+the\s+)?difference\s+between\s+(.+?)\s+and\s+(.+)$", 1, 2)
_add(r"^what\s+is\s+different\s+between\s+(.+?)\s+and\s+(.+)$", 1, 2)
_add(r"^compare\s+(.+?)\s+(?:and|with|to|vs\.?|versus)\s+(.+)$", 1, 2)
_add(r"^how\s+(?:is|are)\s+(.+?)\s+(?:different\s+from|different\s+than|compared\s+to)\s+(.+)$", 1, 2)
_add(r"^how\s+(?:is|are)\s+(.+?)\s+and\s+(.+?)\s+different$", 1, 2)
_add(r"^(.+?)\s+(?:vs\.?|versus)\s+(.+)$", 1, 2)
_add(r"^(.+?)\s+or\s+(.+?)\s+which\s+(?:is|one\s+is)\s+(?:better|best|more\s+suitable|right\s+for\s+me)$", 1, 2)

_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def _clean_operand(text: str) -> str:
    cleaned = _NON_WORD_RE.sub(" ", text).strip()
    return " ".join(cleaned.split())


def _is_bare_program(words: list[str]) -> bool:
    return len(words) == 1 and domain_terms.type_of(words[0]) == "lender"


def _distribute_shared_qualifier(left: str, right: str) -> tuple[str, str]:
    """Copy a trailing qualifier from one operand onto a bare program name
    on the other side, so both sides ask about the same qualified concept.

    "FHA vs VA down payment" extracts as (left="fha", right="va down
    payment") -- a bare regex two-group split has no way to know "down
    payment" belongs to both sides, not just the one it happened to sit
    next to. Left un-fixed, the FHA side searched for "fha" alone and
    surfaced unrelated property-standards text instead of FHA's down
    payment requirement, verified live for "FHA vs VA down payment" and
    "Compare FHA and conventional minimum credit scores". Only applies
    when the bare side is a single recognized program/lender name and the
    qualified side's *own* first word is also one -- that's what confirms
    the qualifier boundary sits right after it, rather than guessing at
    an arbitrary split point in an unrelated multi-word operand.
    """
    left_words = left.split()
    right_words = right.split()
    if _is_bare_program(left_words) and len(right_words) > 1 and domain_terms.type_of(right_words[0]) == "lender":
        qualifier = " ".join(right_words[1:])
        return f"{left} {qualifier}", right
    if _is_bare_program(right_words) and len(left_words) > 1 and domain_terms.type_of(left_words[0]) == "lender":
        qualifier = " ".join(left_words[1:])
        return left, f"{right} {qualifier}"
    return left, right


def extract_comparison_operands(query: str) -> tuple[str, str] | None:
    """Return (left, right) operands, or None if not a comparison query."""
    if not query:
        return None
    q = query.strip(" ?!.,;").strip()
    if not q:
        return None

    for pattern, (left_idx, right_idx) in _PATTERNS:
        match = pattern.match(q)
        if not match:
            continue
        left = _clean_operand(match.group(left_idx))
        right = _clean_operand(match.group(right_idx))
        if not left or not right or left == right:
            continue
        # Guard against degenerate splits (one operand swallowing most of
        # the question text).
        if max(len(left.split()), len(right.split())) > 6:
            continue
        return _distribute_shared_qualifier(left, right)

    return None


def is_comparison(query: str) -> bool:
    """True if the query is a comparison question."""
    return extract_comparison_operands(query) is not None
