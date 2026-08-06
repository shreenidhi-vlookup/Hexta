"""Deterministic conversation coreference resolution.

Resolves pronouns and referring phrases in a follow-up message using the
previous user question. Stateless: the caller supplies the recent
history (list of ``{"question": str, "answer": str|None}`` dicts, oldest
first) and we re-derive the previous turn's subject by re-running the
query pipeline on it.

Conservative by design:
- If the message already names its subject, nothing is rewritten.
- If the message contains no referring expression, nothing is rewritten.
- If the previous turn has no usable subject, nothing is rewritten.

Examples:
- "What is a lifetime mortgage?" → "How is it repaid?"
  resolves to "How is lifetime mortgage repaid?"
- "What is a guarantor?" → "Can they be removed later?"
  resolves to "Can guarantor be removed later?"
"""

from __future__ import annotations

import re

from app.query_processing import entity_extraction as ent
from app.query_processing import pipeline as qp

_PRONOUNS = frozenset(("it", "they", "them", "this", "that", "these", "those"))

_PRONOUN_RE = re.compile(r"\b(?:it|they|them|this|that|these|those)\b")
_REFER_PHRASE_RE = re.compile(r"\b(the above|the same)\b")

# Short, topic-less question that clearly refers to the previous turn.
_BARE_LEADERS = re.compile(
    r"^(what|how|why|when|where|which|who|can|could|will|would|should|is|are|do|does|did)\b"
)

# Words that are not informative as a "topic".
_STOP = frozenset(
    ("what", "how", "why", "when", "where", "which", "who", "whose",
     "is", "are", "was", "were", "do", "does", "did", "can", "could",
     "will", "would", "should", "may", "might", "must",
     "the", "a", "an", "of", "to", "for", "and", "or", "on", "in", "with",
     "about", "there", "it", "they", "them", "this", "that", "these", "those",
     "be", "being", "been", "have", "has", "had", "i", "you", "we", "my",
     "your", "our", "me", "us", "their", "his", "her", "its")
)


def _subject_of(question: str) -> str | None:
    """Derive the topic/entity of the previous question."""
    if not question:
        return None
    plan = qp.process_query(question)
    if not plan.sub_queries:
        return None
    sq = plan.sub_queries[0]
    canonicals = ent.unique_canonicals(sq.entities)
    if canonicals:
        return " ".join(canonicals[:2])
    tokens = [t for t in sq.text.split() if t not in _STOP]
    if tokens:
        return " ".join(tokens[:4])
    return None


def _is_bare_followup(query: str) -> bool:
    """A short question with no topic of its own (refers to previous turn)."""
    words = query.split()
    if not words or len(words) > 6:
        return False
    return bool(_BARE_LEADERS.match(words[0]))


def resolve_references(query: str, history: list[dict] | None) -> str:
    """Resolve referring expressions in ``query`` against ``history``.

    Returns the (possibly rewritten) query. Never raises.
    """
    if not history:
        return query

    q = (query or "").strip()
    if not q:
        return query

    subject = _subject_of(history[-1].get("question", ""))
    if not subject:
        return query

    q_lower = q.lower()
    if subject.lower() in q_lower:
        return query  # already names its subject

    # 1. Explicit referential phrase ("the above", "the same").
    if _REFER_PHRASE_RE.search(q_lower):
        return _REFER_PHRASE_RE.sub(subject, q)

    # 2. Pronoun present → replace with the previous subject.
    if _PRONOUN_RE.search(q_lower):
        return _PRONOUN_RE.sub(subject, q)

    # 3. Bare follow-up ("what are the risks?", "what happens next?").
    #    Only rewrite when the follow-up has no topic of its own, so a
    #    genuinely new short question ("what is a credit score?") is not
    #    polluted with the previous subject.
    if _is_bare_followup(q_lower):
        plan = qp.process_query(q)
        topic = ent.unique_canonicals(plan.sub_queries[0].entities) if plan.sub_queries else []
        if not topic:
            return f"{subject} {q}"
        return query

    return query
