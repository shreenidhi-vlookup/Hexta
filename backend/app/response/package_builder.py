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
from app.query_processing.relevance import relevance_factor
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

    # Answer phrase from the most relevant cleanly-starting excerpt (single
    # traced sentence). A chunk that opens mid-word is skipped so the
    # answer never starts with a fragment like "l mortgages..." or "ents.".
    #
    # "Most relevant to query_text", not just "top-ranked by RRF" -- the
    # #1 candidate by vector/BM25 score is often a generic framing sentence
    # ("The VA funding fee varies based on down payment amount...") while a
    # lower-ranked excerpt holds the actual specific answer (a table row:
    # "0% down  2.15%"). Plain word-overlap relevance alone isn't enough to
    # prefer the specific one, though -- a framing sentence that happens to
    # repeat the same domain words ("VA", "funding fee", "down payment")
    # can score just as relevant, or higher, than the terse specific
    # answer. When the query itself is asking about a figure (contains a
    # digit -- "0% down payment", "$500", "30 days"), an excerpt that
    # actually contains a number is preferred outright over one that
    # doesn't, before relevance breaks any remaining tie: a query asking
    # for a specific number should lead with a number, not general
    # information, whenever the retrieved evidence has one to offer.
    # A relevance tie is common when a checklist item carries its parent
    # sentence as context (see checklist_chunker.py) -- the item and its
    # own preamble excerpt then share identical relevance, since the
    # item's text is "preamble + bullet". Left alone, rank order would
    # pick the *preamble itself*: a teaser sentence ending in ":"
    # ("...following categories:") that promises a list without ever
    # delivering it, when the excerpt one rank down is the same teaser
    # *plus* an actual item from that list. So among excerpts tied on the
    # signals above, one that doesn't trail off with a colon wins --
    # relevance is rounded first so near-equal floats count as tied
    # rather than one deciding the whole comparison by a fraction.
    #
    # Ties on all signals (the common case) fall back to rank order via
    # max()'s stable first-match behavior, so unaffected queries -- most
    # of them -- see no change at all.
    clean_excerpts = [e for e in excerpts if _starts_cleanly(e.text)]
    query_wants_number = bool(re.search(r"\d", query_text or ""))

    def _phrase_rank(e: Excerpt) -> tuple:
        rel = round(relevance_factor(query_text, e.text), 2)
        not_teaser = not e.text.rstrip().endswith(":")
        if query_wants_number:
            return (bool(re.search(r"\d", e.text)), rel, not_teaser)
        return (rel, not_teaser)

    def _phrase_from(e: Excerpt) -> str:
        if e.source.chunk_type in ("table", "checklist"):
            # _extract_answer_phrase is prose-oriented: it looks for a
            # sentence ending in terminal punctuation. Table rows and
            # checklist items are both short, substantive fragments with
            # no such punctuation -- every row/item got classified as
            # "just a heading" and skipped, so this always returned ""
            # for them. An empty answer_phrase makes search.py's
            # _decide_routing() force no_answer regardless of confidence,
            # silently discarding correctly-retrieved, high-confidence
            # evidence (verified live for both: an LTV table at 98.4%
            # confidence and a "two-to-four unit" checklist item at 99.2%
            # both surfaced "No answer found"). Both are already complete,
            # atomic units of evidence on their own -- their own truncated
            # verbatim text stands in as the phrase directly. No
            # synthesis, just the same length cap applied to prose.
            return _truncate(e.text, 200)
        return _extract_answer_phrase(e.text)

    # Excerpts are tried in _phrase_rank order (best first), falling
    # through to the next one whenever a candidate can't produce a phrase
    # at all -- not just when it isn't the top choice. A chunk can be a
    # bare section heading with no body ("Manufactured Home Additional
    # Requirements", "Rescission Period") that ranks #1 on relevance
    # (it repeats the query's own words) but is correctly recognized as
    # "just a heading" and yields "". The old code committed to whichever
    # excerpt _phrase_rank preferred and gave up if that one came back
    # empty, discarding two more excerpts sitting right below it that
    # would have worked fine (verified live: both cases had a 97%+
    # confidence excerpt one or two ranks down with real answer content).
    answer_phrase = ""
    for candidate in sorted(clean_excerpts, key=_phrase_rank, reverse=True):
        answer_phrase = _phrase_from(candidate)
        if answer_phrase:
            break
    else:
        # Nothing usable came from any clean-starting excerpt (including
        # when there were none at all -- every excerpt opened mid-word).
        # Fall back to the top-ranked excerpt regardless, same as before
        # this whole selection logic existed: a mid-word-opening excerpt
        # is still better than surfacing no answer at all when it's all
        # there is.
        if excerpts:
            answer_phrase = _phrase_from(excerpts[0])

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
