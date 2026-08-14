"""Vocabulary-gated typo correction.

Strategy: correct a *single token* only when it is NOT already a known
term/acronym/common word AND it has a strong fuzzy match in the domain
vocabulary. Everything else is left untouched:

- numbers, percentages, dollar amounts are never corrected
- known acronyms (ltv, dti, fha, va, usda, apr ...) are protected
- unknown words with no near match are left as-is (the search engine is
  still typo-tolerant via tsvector stemming and vector similarity)

A small "glued word" recovery pass fixes tokens like ``whatis`` or
``creditscore`` by splitting them into two known vocabulary words.

``rapidfuzz`` is a small, C-accelerated, actively-maintained library —
far lighter than SymSpell or any model, and fast enough for query-time
use on a shared micro instance.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz, process

from app.query_processing import corpus_vocab, domain_terms

_MIN_TOKEN_LEN_FOR_CORRECTION = 4
# Strong-match threshold. Below this the candidate is too different to
# trust; we keep the user's spelling rather than risk a wrong "fix".
# 80 is chosen so that single-character edits in 4-6 char tokens (e.g.
# "inocme" → "income" at 83.3) are caught, while random strings are not.
_RATIO_THRESHOLD = 80
# Phrase-level threshold (multi-word aliases) is higher — replacing a
# whole phrase is more invasive.
_PHRASE_RATIO_THRESHOLD = 92

_TOKEN_RE = re.compile(r"[a-z]+")
_ALPHA_RE = re.compile(r"^[a-z]+$")

def _multiword_word_vocab() -> set[str]:
    """Single words that appear inside a multi-word alias or canonical.

    Without these, a correctly-spelled common word that happens to sit
    inside a phrase (e.g. "finance" from "bridging finance") is absent
    from the vocab and can be fuzzy-matched into a DIFFERENT word that
    only shares characters ("finance" → "refinance" at 87.5). Adding the
    component words makes them correction targets too, so a typo like
    "bridgng finance" can be repaired to "bridging finance".
    """
    words: set[str] = set()
    for alias in domain_terms.multiword_aliases():
        for w in alias.split():
            if _ALPHA_RE.match(w) and len(w) >= _MIN_TOKEN_LEN_FOR_CORRECTION:
                words.add(w)
    for canon in domain_terms.DOMAIN_TERMS:
        for w in canon.split():
            if _ALPHA_RE.match(w) and len(w) >= _MIN_TOKEN_LEN_FOR_CORRECTION:
                words.add(w)
    return words


# Vocabulary for token-level correction: only SINGLE-WORD entries.
# Multi-word phrases are handled by the phrase-level pass, not here.
# Using only single words prevents low ratios when comparing a short
# token against a multi-word alias (e.g. "credt" vs "credit score").
_CORRECTION_VOCAB: list[str] = sorted(
    set(a for a in domain_terms.aliases() if " " not in a)
    | set(d for d in domain_terms.DOMAIN_TERMS.keys() if " " not in d)
    | domain_terms.COMMON_WORDS
    | _multiword_word_vocab()
)
_VOCAB_SET: set[str] = set(_CORRECTION_VOCAB)

# Multi-word vocabulary for phrase-level protection (all aliases + canonicals).
# Used to skip phrases that are already known terms.
_MULTIWORD_VOCAB: set[str] = set(
    set(alias for alias in domain_terms.aliases() if " " in alias)
    | set(canon for canon in domain_terms.DOMAIN_TERMS if " " in canon)
)

# Multi-word aliases for the phrase-level fix pass.
_MULTIWORD_ALIASES: list[str] = sorted(
    domain_terms.multiword_aliases(), key=len, reverse=True
)

# Word → set of words it co-occurs with in a known domain phrase.
# Used to prefer a correction that completes a term the query already
# hints at (e.g. "credit *" → "score", not the string-closer "escrow").
_PHRASE_PARTNERS: dict[str, set[str]] = {}
for _phrase in set(domain_terms.aliases()) | set(domain_terms.DOMAIN_TERMS):
    _words = _phrase.split()
    for _w in _words:
        _PHRASE_PARTNERS.setdefault(_w, set()).update(x for x in _words if x != _w)

# Score bonus a candidate earns when it completes a domain term hinted by
# a neighbouring word. Big enough to win over a generic string match even
# when the raw ratio is below threshold (e.g. "scro"→"score" at 66.7).
_CONTEXT_BONUS = 20.0

# Question starters are never domain content words, so a short typo that
# fuzzy-matches one ("wht"/"wat" → "what") can be fixed safely. Domain
# acronyms (dti/ltv/apr/fha...) top out at ratio ≤67, far below this, so
# they are never touched.
_SHORT_STARTER_THRESHOLD = 85
_QUESTION_STARTER_VOCAB: list[str] = sorted(domain_terms.QUESTION_STARTERS)

def _is_protected(token: str) -> bool:
    """Tokens that must never be rewritten."""
    if not token:
        return True
    if not _ALPHA_RE.match(token):
        return True  # contains digits / symbols / $ / % etc.
    if token in _VOCAB_SET:
        return True
    # A token that occurs in the indexed corpus is a real term in this
    # deployment's domain, not a typo -- even when it is absent from the
    # static lists above. Without this, an entity specific to the user's
    # documents can be fuzzy-matched into an unrelated dictionary word
    # ("respa" -> "repay" at exactly the 80.0 threshold), which rewrites
    # the query before any search runs. See corpus_vocab.
    if token in corpus_vocab.active_vocabulary():
        return True
    # Protect common English plurals: if dropping a trailing "s" yields
    # a known word, treat the plural as protected too.
    if len(token) > 4 and token.endswith("s") and token[:-1] in _VOCAB_SET:
        return True
    if len(token) < _MIN_TOKEN_LEN_FOR_CORRECTION:
        return True
    return False


def _edit_is_plausible(token: str, candidate: str) -> bool:
    """Reject "corrections" that change the word rather than repair it.

    A typo is a substitution/transposition/dropped character, so a real
    fix stays close to the original *length*. A candidate that bolts a
    whole morpheme on ("paid" → "repaid", "finance" → "refinance") is a
    different word that happens to score well: both sit right at the 80.0
    acceptance threshold, since a short token shares most of its
    characters with its own prefixed form.

    Allowing one character of slack (more for longer tokens, where a
    dropped syllable is a plausible typo) keeps genuine repairs like
    "credt" → "credit" and "investmnt" → "investment" working.
    """
    return abs(len(candidate) - len(token)) <= max(1, len(token) // 4)


def _split_glued(token: str) -> str | None:
    """Return a space-joined split if the token is two known words glued."""
    if len(token) < 5:
        return None
    for i in range(2, len(token) - 1):
        left, right = token[:i], token[i:]
        if len(left) < 2 or len(right) < 2:
            continue
        if left in _VOCAB_SET and right in _VOCAB_SET:
            return f"{left} {right}"
    return None


def _context_pairs(word: str, neighbors: set[str]) -> bool:
    """True if ``word`` completes a known domain phrase with a neighbour.

    e.g. for token "scro" next to "credit", the candidate "score" is a
    partner of "credit" (via "credit score"), so it is boosted; "escrow"
    is not, so the correct word wins even though it is string-farther.
    """
    partners = _PHRASE_PARTNERS.get(word)
    if not partners:
        return False
    return any(n in partners for n in neighbors)


def _correct_token(token: str, neighbors: set[str] | None = None) -> str:
    # Short typo of a question starter (e.g. "wht"/"wat" → "what"). Runs
    # before the generic protection so short tokens can be repaired too,
    # while domain acronyms are untouched (their ratios are far lower).
    if len(token) == 3:
        best, score, _ = process.extractOne(
            token, _QUESTION_STARTER_VOCAB, scorer=fuzz.ratio
        )
        if score >= _SHORT_STARTER_THRESHOLD:
            return best
    if _is_protected(token):
        return token
    # Try glued-word recovery FIRST — "whatis" should split to "what is",
    # not get fuzzy-matched to "what" (which drops the "is" entirely).
    glued = _split_glued(token)
    if glued:
        return glued
    neighbors = neighbors or set()
    matches = process.extract(token, _CORRECTION_VOCAB, scorer=fuzz.ratio, limit=15)
    best: str | None = None
    best_eff = -1.0
    for cand, score, _ in matches:
        if not _edit_is_plausible(token, cand):
            continue
        bonus = _CONTEXT_BONUS if _context_pairs(cand, neighbors) else 0.0
        effective = score + bonus
        if effective < _RATIO_THRESHOLD:
            continue
        if effective > best_eff:
            best, best_eff = cand, effective
    return best if best is not None else token


def _phrase_edit_is_plausible(window: list[str], alias_tokens: list[str]) -> bool:
    """True when rewriting ``window`` to ``alias_tokens`` only repairs typos.

    Whole-window fuzzy matching is blind to *which* word changed, so a
    high score can hide a rewrite that inserts meaning rather than fixing
    a spelling: "a loan" scores 92.3 against the alias "va loan" (over the
    92 threshold) purely because five of six characters line up, and the
    replacement silently turns a generic question into a VA-loan question.

    A token the token-level pass refuses to touch (an article, an
    acronym, a number) must not be rewritable by the phrase pass either --
    protection has to hold at every level or it is not protection. Tokens
    that are eligible for correction still have to look like typo repairs
    of their counterparts.
    """
    for original, replacement in zip(window, alias_tokens):
        if original == replacement:
            continue
        if _is_protected(original):
            return False
        if not _edit_is_plausible(original, replacement):
            return False
    return True


def _correct_multiword_phrases(text: str) -> str:
    """Fix misspelled multi-word phrases using a sliding-window match.

    Only replaces a window when the fuzzy match is very strong and the
    window is not already an exact alias.

    Uses a single pass with position tracking to prevent infinite loops
    between aliases that fuzzy-match each other (e.g. "credit score" vs
    "credit scores"). Each token position can only be replaced once per
    pass, and we cap iterations as a safety net.
    """
    tokens = text.split()
    if len(tokens) < 2:
        return text

    _MAX_PHRASE_PASSES = 3
    for _ in range(_MAX_PHRASE_PASSES):
        changed = False
        used_positions: set[int] = set()

        for alias in _MULTIWORD_ALIASES:
            alias_tokens = alias.split()
            n = len(alias_tokens)
            for i in range(len(tokens) - n + 1):
                if any(pos in used_positions for pos in range(i, i + n)):
                    continue
                window = " ".join(tokens[i : i + n])
                if window == alias or window in _MULTIWORD_VOCAB:
                    for pos in range(i, i + n):
                        used_positions.add(pos)
                    continue
                if not _phrase_edit_is_plausible(tokens[i : i + n], alias_tokens):
                    continue
                if fuzz.ratio(window, alias) >= _PHRASE_RATIO_THRESHOLD:
                    tokens[i : i + n] = alias_tokens
                    for pos in range(i, i + n):
                        used_positions.add(pos)
                    changed = True
                    break
            if changed:
                break

        if not changed:
            break

    return " ".join(tokens)


def correct(text: str) -> str:
    """Correct spelling of a normalized (lowercased) query string.

    Order: token-level correction, then multi-word phrase repair, then
    collapse any whitespace introduced.
    """
    if not text:
        return text
    tokens = text.split()
    corrected_tokens: list[str] = []
    for i, token in enumerate(tokens):
        neighbors: set[str] = set()
        if i > 0:
            neighbors.add(tokens[i - 1])
        if i + 1 < len(tokens):
            neighbors.add(tokens[i + 1])
        corrected_tokens.append(_correct_token(token, neighbors))
    joined = " ".join(corrected_tokens)
    joined = _correct_multiword_phrases(joined)
    return re.sub(r"\s+", " ", joined).strip()
