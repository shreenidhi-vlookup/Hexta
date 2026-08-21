"""Grounding validator — the gate every synthesized answer must pass.

An LLM answer may only replace the extractive answer phrase when EVERY
factual sentence in it is supported by the retrieved evidence. This is
what makes the LLM tier safe: a synthesis that drifts outside the
evidence fails here and the user sees the extractive answer instead —
the system's failure mode is "less fluent", never "fabricated".

Method (deliberately conservative, no model): split the candidate into
sentences, extract content terms (question starters, stop words and
generic verbs removed — same vocabulary discipline as
query_processing/relevance.py), and require each sentence to share at
least GROUNDING_MIN_OVERLAP of its content terms with the union of the
evidence passages. Sentences that are pure connective tissue ("This
means lower monthly costs.") have few or no content terms and pass on
structure; sentences carrying numbers or domain terms that appear
nowhere in the evidence fail.

A corpus-vocabulary filter (like relevance.py's) is intentionally NOT
applied here: for grounding, an unfamiliar term in the *candidate* is
suspicious by definition — it may be hallucinated. Absence from the
corpus cannot excuse it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.query_processing import domain_terms

# Minimum fraction of a sentence's content terms that must appear in the
# evidence for that sentence to count as grounded. Configuration, not a
# constant: recalibrate alongside the benchmark when the LLM tier is
# enabled (CLAUDE.md rule 7).
GROUNDING_MIN_OVERLAP: float = 0.6

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-z0-9.]+")

# Generic verbs/connectors that carry no checkable claim content.
_SOFT_TERMS = frozenset((
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "can", "could", "should", "may",
    "might", "must", "shall",
    "this", "that", "these", "those", "it", "its", "they", "them", "their",
    "there", "here", "which", "who", "whom", "whose", "what", "when", "where",
    "how", "why",
    "and", "or", "but", "also", "however", "therefore", "thus", "so", "if",
    "then", "because", "while", "during", "under", "over", "about",
    "mean", "means", "meaning", "refers", "refer", "known", "called",
    "typically", "generally", "usually", "often", "may",
    "borrower", "borrowers", "lender", "lenders", "loan", "loans",
    "requirement", "requirements", "document", "documents",
))


@dataclass
class GroundingVerdict:
    passed: bool
    grounded_sentences: int = 0
    failed_sentences: list[str] = field(default_factory=list)


def _content_terms(sentence: str) -> set[str]:
    """Lowercased content terms of a sentence: words minus stop/soft terms."""
    words = set(_WORD_RE.findall(sentence.lower()))
    return {
        w for w in words
        if w not in domain_terms.COMMON_WORDS
        and w not in domain_terms.QUESTION_STARTERS
        and w not in _SOFT_TERMS
        and len(w) > 1
    }


# Inline citation markers the synthesis prompt requires ("[1]", "[2]") —
# stripped before checking, otherwise the marker's own digit reads as an
# unsupported number.
_CITATION_RE = re.compile(r"\s*\[\d+\]")


def check_grounding(answer_text: str, evidence_texts: list[str]) -> GroundingVerdict:
    """Validate that every factual sentence is supported by the evidence.

    Numbers are checked as strings with currency/percent decoration
    stripped ("3.5%", "$1,500" → "3.5", "1500") so a paraphrase like
    "3.5 percent" still matches "3.5%" in the source.
    """
    answer_text = _CITATION_RE.sub("", answer_text or "")
    evidence_blob = " ".join(evidence_texts or []).lower()
    evidence_numbers = set(re.findall(r"\d[\d,]*(?:\.\d+)?", evidence_blob))

    failed: list[str] = []
    grounded = 0

    for sentence in _SENTENCE_SPLIT_RE.split(answer_text or ""):
        sentence = sentence.strip()
        if not sentence:
            continue
        terms = _content_terms(sentence)
        # Pure connective sentence — nothing checkable, counts as grounded.
        if not terms:
            grounded += 1
            continue

        numbers = {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", sentence)}
        unsupported_numbers = {n for n in numbers if n not in evidence_numbers}

        present = sum(1 for t in terms if t in evidence_blob)
        overlap = present / len(terms)

        if overlap >= GROUNDING_MIN_OVERLAP and not unsupported_numbers:
            grounded += 1
        else:
            failed.append(sentence)

    return GroundingVerdict(
        passed=not failed,
        grounded_sentences=grounded,
        failed_sentences=failed,
    )
