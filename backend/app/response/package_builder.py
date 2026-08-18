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
from app.query_processing import domain_terms
from app.query_processing.relevance import (
    _RELEVANCE_STOP,
    content_term_groups,
    relevance_factor,
    term_present,
    term_stem_candidates,
)
from app.ranking.rrf import RRF_K, RankedCandidate
from app.ranking.weights_config import DEFAULT_WEIGHTS


def _normalize_rrf_score(rrf_score: float) -> float:
    """Normalize an RRF score to a 0-100 confidence scale.

    The maximum possible RRF score is (bm25_weight + vector_weight)/(K+1),
    achieved when a candidate ranks first in both the BM25 and vector
    lists. We normalize against that theoretical maximum and cap at 100.

    The weight sum must come from the same config rank_fusion() uses, not
    a hardcoded 2.0: that constant was only correct while fusion summed
    the two reciprocal ranks unweighted. Once weights were applied (they
    sum to 1.0 by default), a hardcoded 2.0 halved every confidence in
    the system -- verified live, six previously-answerable queries all
    dropped from 82-99% to 41-50% and routed to no_answer purely from
    this mismatch.
    """
    max_rrf = (DEFAULT_WEIGHTS.bm25_weight + DEFAULT_WEIGHTS.vector_weight) / (RRF_K + 1)
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

    The opener check only applies when the sentence has no terminal
    punctuation of its own to go on (a heading-style fragment, e.g. "What
    is a lifetime mortgage" typo'd without its "?"). Several wh-openers
    ("when", "which", "where", "who") are equally common as the start of a
    *statement* using them as a relative pronoun or subordinating
    conjunction rather than an interrogative -- "When a borrower uses a
    second mortgage..., underwriters calculate the combined loan-to-value
    ratio..." is a complete, correct answer sentence, not a question, even
    though it opens with "When". A sentence ending in real terminal
    punctuation (".", "!") is, in formatted prose, essentially never an
    actual question -- genuine questions end in "?" -- so once there's a
    non-"?" terminator to go on, that settles it over the opener guess
    (verified live: this was silently discarding the one correct sentence
    in an excerpt and letting an unrelated sentence win instead).
    """
    s = sentence.strip()
    if not s:
        return False
    if s.endswith("?"):
        return True
    if s[-1] in _TERMINAL_PUNCT:
        # Ends in "." or "!" -- a statement, regardless of its opening word.
        return False
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


_WRAPPED_LINE_RE = re.compile(r"(?<=[^\s.!?])\n(?=[a-z])")


def _join_wrapped_lines(text: str) -> str:
    """Collapse a source document's typographic hard-wraps back into prose.

    Chunk text can carry the source's original line-wrap newlines verbatim
    (this repo's chunkers don't rejoin wrapped paragraph lines). Downstream,
    both `_strip_leading_heading` and `_SENTENCE_RE` treat *any* `\\n` as a
    real structural break -- correct for a heading/label stacked above its
    sentence (see `TestExtractAnswerPhraseMultilineChunk`), wrong for a
    single sentence that merely wrapped at ~75 columns. Verified live: "Rate
    Lock Window: A client may lock a rate up to 6 months before their\\n
    current deal ends..." -- `_strip_leading_heading` saw the first wrapped
    line (70 chars, no terminal punctuation) and dropped it whole as a
    "heading", discarding the "6 months" the question was asking for.

    A wrapped continuation line is distinguished from a genuine next
    heading/label/sentence by two signals together: the line above doesn't
    end in terminal punctuation, and the next line opens with a lowercase
    word (headings and new sentences are capitalized). Only then is the
    newline replaced with a space. A blank-line paragraph break is
    untouched regardless -- the character right after such a `\\n` is
    another `\\n`, never a lowercase letter, so it can't match.
    """
    return _WRAPPED_LINE_RE.sub(" ", text)


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
    """True when the excerpt begins at a plausible sentence/unit boundary.

    Chunks produced from the hard-cut generated QA docs often open
    mid-word ("l mortgages", "ents.", "ransfer"); those make poor
    answer sources. A clean start is an uppercase letter, a digit, an
    opening quote, a bullet/number marker, or a markdown table row.

    Markdown table chunks (chunk_type == "table") intentionally start
    with "|" -- that's not a mid-word truncation artifact, it's the
    complete, well-formed start of the row. Without recognizing it, every
    table excerpt failed this check and was silently dropped from
    ``clean_excerpts`` in build_response_package(), which meant table
    excerpts never took part in relevance-based phrase-source ranking and
    always fell back to whichever table happened to rank first by raw
    retrieval score -- regardless of which one actually answered the
    question. Verified live: for "What is the minimum down payment for a
    VA loan?", the correct table (relevance 0.6) was excerpt #2 and the
    wrong one (relevance 0.4) was excerpt #1; both got excluded here, so
    the excerpt-order fallback picked the wrong one every time.
    """
    stripped = (text or "").lstrip()
    if not stripped:
        return False
    first = stripped[0]
    return (
        first.isupper()
        or first.isdigit()
        or first in "\"'"
        or stripped.startswith(("*", "-", "\u2022", "|"))
    )


def _term_match_count(sentence: str, groups: list[set[str]]) -> int:
    """How many query content *concepts* appear in ``sentence``.

    Counts term groups, not flat terms, so an abbreviation and its
    spelled-out expansion count once between them (see
    relevance.content_term_groups). Scoring the flat terms instead lets a
    sentence win just by spelling an abbreviation out: for "when is PMI
    automatically removed?", the sentence that merely *defines* the term
    ("...requires Private Mortgage Insurance (PMI).") matched four flat
    terms -- pmi, private, mortgage, insurance -- while the sentence that
    actually answers ("PMI can be removed automatically once the loan
    balance reaches 78%...") matched three, so the definition won and the
    answer was never surfaced.
    """
    hay = sentence.lower()
    return sum(1 for g in groups if any(term_present(t, hay) for t in g))


_QUERY_WORD_RE = re.compile(r"[a-z0-9']+")


def _query_phrases(query_text: str | None) -> list[str]:
    """Adjacent content-word pairs from the query ("second home").

    Bag-of-words relevance cannot tell a compound concept from its words
    appearing separately: for "What is the maximum LTV for a second
    home?", a paragraph about a "second mortgage" alongside a "home
    equity line of credit" contains both "second" and "home" and scores a
    perfect 1.0, identical to the table that actually lists "Second home
    | 90%". Tracking the query's adjacent word pairs gives a signal that
    separates them -- only the table contains the pair contiguously.
    """
    if not query_text:
        return []
    words = _QUERY_WORD_RE.findall(query_text.lower())
    content = [
        (i, w) for i, w in enumerate(words)
        if w not in _RELEVANCE_STOP and w not in domain_terms.QUESTION_STARTERS
    ]
    phrases: list[str] = []
    for (i, w1), (j, w2) in zip(content, content[1:]):
        if j == i + 1:  # literally adjacent in the query
            phrases.append(f"{w1} {w2}")
    return phrases


def _phrase_pattern(phrase: str) -> re.Pattern:
    """Adjacency regex for a two-word phrase, tolerant of word endings.

    Each word is reduced to its shortest stem and allowed a suffix, so
    "hvac filters" still matches "HVAC filter replacement". Exact
    substring matching was too brittle for this: the plural in the query
    made the phrase miss the very table row that answered it ("| HVAC
    filter replacement | Every 1-3 months |") while matching a checklist
    that happened to use the plural ("Replacing light bulbs and HVAC
    filters"), handing the tie to the wrong chunk.
    """
    parts = []
    for word in phrase.split():
        root = min(term_stem_candidates(word), key=len)
        parts.append(re.escape(root) + r"\w*")
    return re.compile(r"\b" + r"\s+".join(parts), re.IGNORECASE)


def _phrase_hits(text: str, phrases: list[str]) -> int:
    """How many query compound phrases appear (stem-tolerant) in ``text``."""
    if not phrases:
        return 0
    hay = text.lower()
    return sum(1 for p in phrases if _phrase_pattern(p).search(hay))


def _score_key(text: str, groups: list[set[str]], wants_number: bool) -> tuple:
    """Ranking key for a candidate fragment: numbers first, then coverage.

    When the query itself contains a figure ("...with a 580 credit
    score", "0% down"), a fragment that carries a number outranks one
    that doesn't, before term coverage breaks the remaining tie. This is
    the same rule _phrase_rank already applies when choosing *between*
    excerpts, applied again *within* one -- without it, the framing
    sentence of a chunk reliably beats the line holding the answer,
    because naming the topic uses more of the question's words than
    stating the figure does. Verified live: for "What down payment do I
    need for an FHA loan with a 580 credit score?", the intro
    ("...the down payment required depends directly on the applicant's
    credit score:") covers six query concepts while the item that
    answers ("- Borrowers with a credit score of 580 or higher qualify
    for the minimum down payment of 3.5%") covers five, so the question
    was answered with a restatement of itself and the 3.5% was truncated
    away entirely.
    """
    has_number = bool(re.search(r"\d", text)) if wants_number else False
    return (has_number, _term_match_count(text, groups))


def _best_snippet(
    sentence: str, groups: list[set[str]], max_chars: int, wants_number: bool = False
) -> str:
    """Pick the ``max_chars``-wide, word-aligned window of ``sentence`` that
    covers the most query content terms, instead of always the prefix.

    A single long run-on sentence can bury the actual answer well past
    where a naive prefix truncation would cut off -- e.g. scene-setting
    clauses first ("Recent bankruptcies, foreclosures, or short sales
    impose mandatory waiting periods before a borrower is eligible for a
    new mortgage,...") with the specific figure only in the back half
    ("...two years for FHA loans following a Chapter 7 bankruptcy
    discharge..."). A plain prefix cut can land before the figure and
    leave the query's own terms out of the phrase entirely, which then
    also tanks the query<->answer relevance score downstream. Falls back
    to a plain prefix truncation when no window beats it (no query terms,
    or none of them appear anywhere in the sentence).

    Text that already fits is returned untouched: windowing exists to
    decide *what to drop* when something must be dropped, so applying it
    to a fragment that needs no cut would only shorten a complete,
    verbatim answer (a short checklist item would come back as its first
    few words plus an ellipsis).
    """
    if len(sentence) <= max_chars:
        return sentence
    words = sentence.split()
    if not words or not groups:
        return _truncate(sentence, max_chars)
    start = 0
    best_start, best_end = 0, -1
    best_score: tuple = (False, -1)
    # Window length is the last tiebreaker: among windows covering the
    # same concepts, keep the longest one that still fits. Preferring the
    # first/shortest instead throws away budget that is already paid for
    # and can cut the answer off right after the words it matched on --
    # "...applicants generally fall into one of the following categories:
    # Veterans who served..." scores its maximum at "Eligibility for a
    # VA-backed loan", so the phrase stopped there and dropped the item
    # the reader actually needed.
    best_key: tuple = (False, -1, -1)
    for end in range(len(words)):
        while start < end and len(" ".join(words[start : end + 1])) > max_chars:
            start += 1
        window = " ".join(words[start : end + 1])
        if len(window) > max_chars:
            continue
        score = _score_key(window, groups, wants_number)
        key = (*score, len(window))
        if key > best_key:
            best_key, best_score, best_start, best_end = key, score, start, end
    if best_end < 0 or best_score <= (False, 0):
        return _truncate(sentence, max_chars)
    snippet = " ".join(words[best_start : best_end + 1])
    prefix = "…" if best_start > 0 else ""
    suffix = "…" if best_end < len(words) - 1 else ""
    return f"{prefix}{snippet}{suffix}"


_TABLE_SEPARATOR_RE = re.compile(r"^[|\s:-]+$")


def _table_row_phrase(
    text: str, groups: list[set[str]], max_chars: int, wants_number: bool = False
) -> str:
    """Pick the single table row that best answers the query.

    A markdown table chunk is a stack of independent rows, not prose: the
    row that answers the question is rarely the first one, but the phrase
    for a table used to be a plain prefix truncation of the whole chunk.
    That returns the header plus whichever rows happen to come first, and
    cuts off the relevant row entirely when it sits lower down -- verified
    live: "What is the minimum down payment for a VA loan?" produced a
    phrase containing the Conventional and FHA rows while the "| VA | 0%
    for eligible borrowers | 100% |" row was truncated away, so the answer
    never showed the figure it was asked for.

    Each data row is scored by query-term coverage and the best one is
    returned verbatim -- a table row is already a complete, atomic unit of
    evidence (the full table is always visible in the source excerpt below
    the answer). Separator rows ("|---|---|") are skipped.

    The first row is the header and is excluded from selection whenever
    the table has data rows at all: its cells are column *names*, so it
    reliably out-scores every data row on query-term overlap while
    containing no answer -- for "what is the max ltv for investment
    property", the header "Property Type | Max LTV | Min Down Payment"
    matches three query terms and the row that actually answers
    ("Investment Property | 85% | 15%") matches two. This is the same
    principle _is_heading applies to prose: a label is never an answer.

    Falls back to the previous whole-chunk truncation when there are no
    data rows, no query terms, or no data row matches any query term.
    """
    rows = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not _TABLE_SEPARATOR_RE.match(line.strip())
    ]
    data_rows = rows[1:] if len(rows) > 1 else rows
    if not data_rows or not groups:
        return _truncate(text, max_chars)
    best = max(data_rows, key=lambda r: _score_key(r, groups, wants_number))
    if _score_key(best, groups, wants_number) <= (False, 0):
        return _truncate(text, max_chars)
    return _truncate(best, max_chars)


def _extract_answer_phrase(
    text: str, max_chars: int = 200, query_text: str | None = None
) -> str:
    """Extract a single answer phrase from a source chunk text.

    Prefers the first substantive (≥ 25 chars) *statement* sentence that
    fits within ``max_chars``, skipping generated footers, chunk-boundary
    fragments, section headings, and questions. A question or a heading is
    never a usable answer, so if the chunk contains only those the result
    is an empty string (the caller routes to ``no_answer``). No synthesis —
    the phrase is always traceable to a source chunk.

    When ``query_text`` is given, "first substantive sentence" is no
    longer a good enough rule on its own: a chunk is often a short
    paragraph of several sentences, and the one that actually answers the
    question is not always the first (e.g. "FHA loans are intended for
    primary residences only. The borrower must occupy the property within
    60 days of closing..." -- the first sentence is on-topic but doesn't
    contain the number the question asked for). In that case *every*
    candidate sentence is scored by how many of the query's content terms
    it contains -- short and over-length alike, scored on its full text
    before any truncation, so the right sentence can't lose purely for
    being long (an earlier version of this scored only the short
    candidates and fell back to the first over-length sentence unscored,
    so a short-but-wrong sentence always beat a long-but-right one; fixed
    after live-verifying the FHA occupancy query still returned the wrong
    "loan limits vary by county" sentence over the correct "must occupy
    within 60 days" one, which is 220 characters). The best-scoring
    sentence wins regardless of length, truncated to a term-dense window
    via ``_best_snippet`` if it's over-length. Ties (including "no query
    term matched anywhere," the common case for queries this scoring
    can't help with) keep the original first-sentence choice, since
    ``max()`` returns the first maximal element on a tie. Without
    ``query_text`` the behavior is unchanged from before this existed.
    """
    if not text:
        return ""
    text = _join_wrapped_lines(text)
    text = _strip_leading_heading(text)
    groups = content_term_groups(query_text) if query_text else []
    wants_number = bool(re.search(r"\d", query_text or ""))

    # (sentence, is_over_length) for every substantive candidate, in
    # source order -- scored together so length never disqualifies a
    # sentence from competing on relevance.
    scored: list[tuple[str, bool]] = []
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
        is_long = len(s) > max_chars
        if not is_long and len(s) < 25:
            fallback.append(s)
            continue
        if not groups:
            # No query to score against: original behavior, first
            # qualifying sentence wins immediately.
            return _truncate(s, max_chars) if is_long else s
        scored.append((s, is_long))

    if scored:
        best, best_is_long = max(
            scored, key=lambda p: _score_key(p[0], groups, wants_number)
        )
        return (
            _best_snippet(best, groups, max_chars, wants_number)
            if best_is_long
            else best
        )
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

    # Compound phrases from the query ("second home") break relevance ties
    # that bag-of-words scoring can't -- see _query_phrases.
    query_phrases = _query_phrases(query_text)

    # Note (measured, kept deliberately): re-sorting excerpts by word
    # overlap here can override the retrieval ranking, which is the
    # stronger signal in principle -- for "What portion of a mortgage
    # represents the amount I still owe excluding interest?" it promotes
    # the Fixed-Rate Mortgage definition (overlap 0.50, it repeats
    # "mortgage" and "interest") over Principal (0.25), which both RRF and
    # the cross-encoder rank first and which is the correct answer.
    #
    # Making retrieval order authoritative here was tried and measured on
    # the 52-case regression matrix: it did not fix that query (Principal's
    # 0.25 overlap then falls under the no-answer floor downstream) and it
    # broke "Which loan type has a payment that never changes?", where the
    # cross-encoder ranks ARM above Fixed-Rate and this re-sort is what
    # currently recovers the right answer. Net -2 cases, so it was
    # reverted. The re-sort is compensating for cross-encoder ranking
    # errors; removing it needs a better top-1 ranker first, not a
    # different tie-break.
    # Confidence (retrieval's own signal) sits between relevance and
    # phrase_hits -- it only ever decides a comparison when relevance has
    # already tied, so it can't override rel the way the reverted "make
    # retrieval order authoritative" attempt did (that removed
    # relevance-based reordering outright and broke a case where the
    # cross-encoder itself ranked wrong -- see the note above). This is
    # narrower: verified live for "Can I lock in an interest rate?" --
    # Rate Lock Window (100% confidence) and Discount Points (93.3%) tied
    # exactly on relevance (0.6667 == 0.6667, plain word overlap), and the
    # phrase_hits signal alone flipped the pick to Discount Points because
    # it happens to contain the query's literal "interest rate" phrase
    # while Rate Lock Window -- the actually-correct, clearly
    # higher-confidence chunk -- says "lock a rate" instead. Confidence
    # breaks that tie before phrase_hits gets a vote.
    def _phrase_rank(e: Excerpt) -> tuple:
        rel = round(relevance_factor(query_text, e.text), 2)
        hits = _phrase_hits(e.text, query_phrases)
        not_teaser = not e.text.rstrip().endswith(":")
        if query_wants_number:
            return (bool(re.search(r"\d", e.text)), rel, e.confidence, hits, not_teaser)
        return (rel, e.confidence, hits, not_teaser)

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
            #
            # Neither is truncated from the top any more, because the
            # answer is rarely in the first 200 characters of either:
            # a table's answer is one row somewhere down the list, and a
            # checklist chunk is "preamble + item" (see
            # checklist_chunker.py) whose preamble alone can fill the
            # whole cap. Verified live: "What down payment do I need for
            # an FHA loan with a 580 credit score?" returned only the
            # intro clause, with the "- Borrowers with a credit score of
            # 580 or higher qualify for the minimum down payment of 3.5%"
            # item cut off -- the question answered with a restatement of
            # itself. Tables select the best row; checklists take the
            # best-covering window. Both stay verbatim.
            groups = content_term_groups(query_text) if query_text else []
            wants_number = bool(re.search(r"\d", query_text or ""))
            if e.source.chunk_type == "table":
                return _table_row_phrase(e.text, groups, 200, wants_number)
            if groups:
                return _best_snippet(e.text, groups, 200, wants_number)
            return _truncate(e.text, 200)
        return _extract_answer_phrase(e.text, query_text=query_text)

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
