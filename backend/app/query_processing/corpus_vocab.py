"""Corpus-derived vocabulary, used to protect real terms from "correction".

``spell_correction`` only rewrites a token when it is *not* a known term.
Its notion of "known" was a static hand-maintained list, so any entity
specific to the user's own documents was invisible to it and eligible to
be fuzzy-matched into an unrelated dictionary word -- "respa" scores
exactly 80.0 (the acceptance threshold) against "repay", so "What is
RESPA?" was searched as "what is repay" and could never retrieve the
RESPA definition that was sitting in the index.

The indexed corpus is the authoritative answer to "is this a real word
here?": a token that literally occurs in the user's documents is a term,
not a typo. Deriving the vocabulary from the corpus makes this work for
every entity in every document uploaded later, rather than requiring each
acronym to be added to a hardcoded list first.

Sourced from two places, both cheap:
  * the distinct words of every searchable chunk. Tokenisation and
    deduplication are done by Postgres, so the result crossing the wire
    is a small word list rather than the whole corpus text.
  * ``term_aliases`` -- the acronym/expansion pairs ingestion already
    extracts.

Deliberately *not* sourced from ``ts_stat`` over the ``fts`` index, which
would be cheaper: that returns stemmed lexemes ("equity" is stored as
"equiti"), and a second consumer of this vocabulary --
``relevance.relevance_factor`` -- looks up raw query terms to decide
which of them the corpus could possibly support. Stemmed entries would
make it silently drop real terms like "equity" from that judgement,
which is a worse failure than the extra scan costs.

Refresh model: a process-level cache with a TTL, recomputed lazily on
access. No background thread and no scheduler, so this does not interfere
with the socket-activated idle-stop design (CLAUDE.md rule 4).
"""

from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger(__name__)

# How long a loaded vocabulary is trusted before it is reloaded. Bounds
# the staleness window after a new document is ingested by the batch
# process (which cannot invalidate this process's cache directly).
TTL_SECONDS = 60.0

_MIN_WORD_LEN = 3
_ALPHA_RE = re.compile(r"^[a-z][a-z'-]*$")

_vocab: frozenset[str] = frozenset()
_concepts: frozenset[str] = frozenset()
_loaded_at: float = 0.0

# Verbs that introduce a request rather than forming part of the concept
# being asked about ("define amortization" -> "amortization").
_REQUEST_VERBS = frozenset(
    ("define", "explain", "describe", "tell", "list", "show", "give",
     "provide", "summarise", "summarize", "what", "whats")
)


def _clean(words) -> frozenset[str]:
    """Normalise raw strings into vocabulary entries.

    Each word also contributes its light stem variants, so membership is
    symmetric with the way callers look terms up. Without this the test
    is one-directional: a lookup of "payment" strips suffixes off the
    *query* term, but the corpus stores the longer form "payments", so
    the match fails and a term the documents plainly cover is treated as
    unsupported -- which silently removes it from the relevance
    denominator and drops the score of a correct answer.
    """
    # Imported here rather than at module scope: relevance imports this
    # module, so a top-level import would be circular.
    from app.query_processing.relevance import term_stem_candidates

    out: set[str] = set()
    for raw in words:
        if not raw:
            continue
        word = str(raw).strip().lower()
        if len(word) < _MIN_WORD_LEN:
            continue
        if not _ALPHA_RE.match(word):
            continue
        out.add(word)
        out.update(c for c in term_stem_candidates(word) if len(c) >= _MIN_WORD_LEN)
    return frozenset(out)


def _clean_concepts(terms) -> frozenset[str]:
    """Normalise defined terms into comparable concept names.

    "Annual Percentage Rate (APR)" contributes both the full name and the
    parenthesised acronym, since a question may use either.
    """
    out: set[str] = set()
    for raw in terms:
        if not raw:
            continue
        term = str(raw).strip().lower()
        for part in re.findall(r"\(([^)]*)\)", term):
            cleaned = part.strip()
            if len(cleaned) >= 2:
                out.add(cleaned)
        term = re.sub(r"\([^)]*\)", " ", term)
        term = re.sub(r"\s+", " ", term).strip(" .,;:")
        if len(term) >= 3:
            out.add(term)
    return frozenset(out)


def install(words, concepts=()) -> None:
    """Set the active vocabulary directly (used by tests and by load())."""
    global _vocab, _concepts, _loaded_at
    _vocab = _clean(words)
    _concepts = _clean_concepts(concepts)
    _loaded_at = time.monotonic()


def reset() -> None:
    """Drop the cached vocabulary."""
    global _vocab, _concepts, _loaded_at
    _vocab = frozenset()
    _concepts = frozenset()
    _loaded_at = 0.0


def active_vocabulary() -> frozenset[str]:
    """The vocabulary currently in effect (empty when never loaded)."""
    return _vocab


def active_concepts() -> frozenset[str]:
    """Terms the corpus explicitly defines (empty when never loaded)."""
    return _concepts


def is_known_concept(text: str) -> bool:
    """True when ``text`` names a concept the corpus defines.

    Leading request verbs are stripped, so "define amortization" and
    "amortization" are recognised alike. This is what lets a coordinated
    list of glossary terms ("amortization, equity, and underwriting") be
    decomposed into one retrieval per term without a hand-maintained list
    of what counts as a concept -- the documents say what they define.
    """
    if not _concepts:
        return False
    words = [w for w in re.split(r"[^a-z0-9'/-]+", (text or "").lower()) if w]
    while words and words[0] in _REQUEST_VERBS:
        words.pop(0)
    if not words:
        return False
    phrase = " ".join(words)
    if phrase in _concepts:
        return True
    # Allow a trailing plural ("arms" -> "arm", "points" -> "point").
    if phrase.endswith("s") and phrase[:-1] in _concepts:
        return True
    return False


def is_stale() -> bool:
    return (time.monotonic() - _loaded_at) > TTL_SECONDS


def load(conn) -> frozenset[str]:
    """Read the corpus vocabulary from Postgres and install it.

    Never raises: a vocabulary problem must degrade spell correction back
    to its previous behaviour, never fail the search request.
    """
    words: set[str] = set()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT lower(w) AS word "
                "FROM document_chunks c, "
                "     unnest(regexp_split_to_array(c.content, '[^A-Za-z'']+')) AS w "
                "WHERE c.is_active AND c.is_approved AND length(w) >= %s",
                (_MIN_WORD_LEN,),
            )
            words.update(row["word"] for row in cur.fetchall())
        with conn.cursor() as cur:
            cur.execute("SELECT alias, canonical FROM term_aliases")
            for row in cur.fetchall():
                words.add(row["alias"])
                # Component words of a multi-word expansion are terms too
                # ("Real Estate Settlement Procedures Act").
                words.update((row["canonical"] or "").split())
        # Terms the corpus explicitly defines. Chunks typed "definition"
        # by the chunker are "Term: body" entries, so the label before the
        # first colon is the defined term.
        concepts: set[str] = set()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT split_part(content, ':', 1) AS term "
                "FROM document_chunks "
                "WHERE chunk_type = 'definition' AND is_active AND is_approved"
            )
            concepts.update(row["term"] for row in cur.fetchall() if row["term"])
    except Exception as exc:  # noqa: BLE001 - never fail the request
        logger.warning("Corpus vocabulary load failed, using static vocab: %s", exc)
        return frozenset()

    install(words, concepts)
    return _vocab


def refresh_if_stale(conn) -> None:
    """Reload the vocabulary when the TTL has expired."""
    if is_stale():
        load(conn)
