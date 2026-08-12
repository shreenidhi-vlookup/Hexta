"""Response package builder.

Assembles retrieved chunks into the ResponsePackage shape. Every field
must trace back verbatim or near-verbatim to a source chunk — no
synthesis (CLAUDE.md doctrine).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field

from app.config import settings
from app.ranking.rrf import RRF_K, RankedCandidate


def _normalize_rrf_score(rrf_score: float) -> float:
    """Normalize an RRF score to a 0-100 confidence scale.

    The maximum possible RRF score is 2/(K+1) when a candidate ranks
    first in both the BM25 and vector lists. We normalize against
    that theoretical maximum and cap at 100.
    """
    max_rrf = 2.0 / (RRF_K + 1)
    if max_rrf <= 0:
        return 0.0
    return min((rrf_score / max_rrf) * 100.0, 100.0)


@dataclass
class Source:
    chunk_id: int
    document_id: int
    title: str
    section: str | None
    chunk_type: str
    department: str
    is_approved: bool
    document_version: int
    page_number: int | None = None
    client_id: str | None = None


@dataclass
class Excerpt:
    text: str
    source: Source
    confidence: float
    bm25_score: float
    vec_score: float


@dataclass
class ResponsePackage:
    response_id: str
    title: str
    answer_phrase: str = ""
    excerpts: list[Excerpt] = field(default_factory=list)
    related_questions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    routing: str = "answer"
    max_excerpt_chars: int = 600


def _truncate(text: str, max_chars: int) -> str:
    """Truncate to max_chars, breaking at a word boundary and signalling
    the cut with an ellipsis so a hard mid-word chop never reaches the UI."""
    if len(text) <= max_chars:
        return text
    head = text[: max_chars - 1]
    space = head.rfind(" ")
    if space > max_chars // 2:
        head = head[:space]
    return head + "…"


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_FOOTER_RE = re.compile(r"^(source:|category:|note:|see\s)", re.IGNORECASE)
_TERMINAL_PUNCT = set(".!?")

# Interrogative openers — a sentence starting with one of these is almost
# always a question ("What is the deferred period?"), never an answer. Kept
# intentionally narrow: words like "Minimum"/"Maximum"/"Tell" are common
# answer openers too, so they are NOT included.
_WH_OPENERS = {
    "what", "how", "why", "when", "where", "who", "whom", "which", "whose",
    "is", "are", "do", "does", "did", "can", "could", "will", "would",
    "should", "may", "might",
}


def _is_question(sentence: str) -> bool:
    """True when a fragment reads as a question (never a usable answer).

    Detects a trailing '?' or an interrogative opener. A genuine answer
    sentence like "Minimum credit score requirements vary by product." is
    not flagged (starts with "Minimum", which is not in the wh-openers).
    """
    s = sentence.strip()
    if not s:
        return False
    if s.endswith("?"):
        return True
    first = s.split(" ", 1)[0].lower().rstrip("?")
    return first in _WH_OPENERS


_HEADING_MAX_CHARS = 80


def _is_heading(sentence: str) -> bool:
    """True when a fragment is a section heading, not an answer body.

    A heading is a *short* line with no terminal punctuation (e.g.
    "Credit Score Requirements", "Identity Verification"). Length is the
    key signal, not just the absence of ".!?" -- a genuine, long answer
    sentence that introduces a list ("Required documents include the
    following items, all of which must be submitted before final
    approval:") also lacks terminal punctuation (it ends in ":"), and
    used to be misclassified as a heading purely because of that,
    leaving no usable answer_phrase for chunks whose lead sentence
    happens to end a checklist intro this way. Real headings are short;
    real sentences aren't, regardless of what they end in.
    """
    s = sentence.strip()
    if not s:
        return False
    if s[-1] in _TERMINAL_PUNCT:
        return False
    return len(s) <= _HEADING_MAX_CHARS


def _strip_leading_heading(text: str) -> str:
    """Drop a leading line that looks like a section heading.

    FAQ/generated chunks are often ``Heading\n<answer sentence>``. When the
    first line is a short, punctuation-free header, it is removed so the
    answer begins at the actual sentence. Otherwise ``text`` is unchanged.
    """
    parts = text.split("\n", 1)
    if len(parts) == 2:
        first = parts[0].strip()
        rest = parts[1].strip()
        if first and rest and first[-1] not in _TERMINAL_PUNCT and len(first) <= 80:
            return rest
    return text


def _starts_cleanly(text: str) -> bool:
    """True when the excerpt begins at a plausible sentence boundary.

    Chunks produced from the hard-cut generated QA docs often open
    mid-word ("l mortgages", "ents.", "ransfer"); those make poor
    answer sources. A clean start is an uppercase letter, a digit, an
    opening quote, or a bullet/number marker.
    """
    stripped = (text or "").lstrip()
    if not stripped:
        return False
    first = stripped[0]
    return (
        first.isupper()
        or first.isdigit()
        or first in "\"'"
        or stripped.startswith(("*", "-", "\u2022"))
    )


def _extract_answer_phrase(text: str, max_chars: int = 200) -> str:
    """Extract a single answer phrase from a source chunk text.

    Prefers the first substantive (≥ 25 chars) *statement* sentence that
    fits within ``max_chars``, skipping generated footers, chunk-boundary
    fragments, section headings, and questions. A question or a heading is
    never a usable answer, so if the chunk contains only those the result
    is an empty string (the caller routes to ``no_answer``). No synthesis —
    the phrase is always traceable to a source chunk.
    """
    if not text:
        return ""
    text = _strip_leading_heading(text)
    fallback: list[str] = []
    for sentence in _SENTENCE_RE.split(text):
        s = sentence.strip()
        if not s or _FOOTER_RE.match(s):
            continue
        if _is_question(s):
            continue
        if _is_heading(s):
            # Section heading — never an answer, regardless of length.
            continue
        if len(s) > max_chars:
            # A long statement (e.g. truncated at a chunk boundary) is still
            # an answer — cut it at a word boundary with an ellipsis.
            return _truncate(s, max_chars)
        if len(s) >= 25:
            return s
        fallback.append(s)
    # No substantive statement: fall back to the first short statement that
    # is not a heading/question (e.g. "Yes."). If everything was a heading
    # or a question, there is no answer.
    for s in fallback:
        if not _is_heading(s) and not _is_question(s):
            return s
    return ""


def build_response_package(
    candidates: list[RankedCandidate],
    query_text: str,
    user_departments: list[str] | None = None,
) -> ResponsePackage:
    """Build a ResponsePackage from ranked candidates.

    - Takes top-N candidates (max_evicence_docs from config)
    - Truncates excerpts to max_excerpt_chars
    - Computes confidence from top candidate's RRF score (0-100)
    - Extracts related questions from query entities
    - Derives answer_phrase from the top excerpt text
    """
    max_docs = settings.max_evidence_docs
    top = candidates[:max_docs]

    excerpts: list[Excerpt] = []
    for c in top:
        confidence = round(_normalize_rrf_score(c.rrf_score), 1)
        excerpts.append(Excerpt(
            text=_truncate(c.content, settings.max_excerpt_chars),
            source=Source(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                title=c.title,
                section=c.section,
                chunk_type=c.chunk_type,
                department=c.department,
                is_approved=c.is_approved,
                document_version=c.document_version,
                client_id=getattr(c, "client_id", None),
            ),
            confidence=round(confidence, 1),
            bm25_score=round(c.bm25_score, 4),
            vec_score=round(c.vec_score, 4),
        ))

    # Response title from the most relevant document
    title = excerpts[0].source.title if excerpts else "No Results Found"

    # Confidence from the top candidate
    top_confidence = excerpts[0].confidence if excerpts else 0.0

    # Answer phrase from the first cleanly-starting excerpt (single traced
    # sentence). A chunk that opens mid-word is skipped so the answer never
    # starts with a fragment like "l mortgages..." or "ents.".
    phrase_excerpt = next(
        (e for e in excerpts if _starts_cleanly(e.text)),
        excerpts[0] if excerpts else None,
    )
    if phrase_excerpt is None:
        answer_phrase = ""
    elif phrase_excerpt.source.chunk_type == "table":
        # _extract_answer_phrase is prose-oriented: it looks for a
        # sentence ending in terminal punctuation. A table's rows are
        # short, substantive fragments with no such punctuation -- every
        # row gets classified as "just a heading" and skipped, so this
        # always returned "" for a table excerpt. An empty answer_phrase
        # makes search.py's _decide_routing() force no_answer regardless
        # of confidence, silently discarding a correctly-retrieved,
        # high-confidence table (verified live: a query whose best match
        # was an LTV-limits table scored 98.4% confidence and still
        # surfaced "No answer found"). Tables are already a complete,
        # atomic unit of evidence (table_chunker.py never splits one
        # mid-row) -- the table's own truncated verbatim text stands in
        # as the phrase directly. No synthesis, just the same length cap
        # _extract_answer_phrase already applies to prose.
        answer_phrase = _truncate(phrase_excerpt.text, 200)
    else:
        answer_phrase = _extract_answer_phrase(phrase_excerpt.text)

    # Generate response_id for audit tracing
    response_id = hashlib.sha256(
        f"{query_text}:{top_confidence}:{uuid.uuid4()}".encode()
    ).hexdigest()[:16]

    return ResponsePackage(
        response_id=response_id,
        title=title,
        answer_phrase=answer_phrase,
        excerpts=excerpts,
        confidence=top_confidence,
        max_excerpt_chars=settings.max_excerpt_chars,
    )
