"""LLM answer synthesis — docs/LLM_INTEGRATION_PLAN.md Stage 1.

OFF by default (``settings.llm_enabled``). When enabled, the top
retrieved evidence chunks are sent to Claude with a strict extraction
prompt; the output must then pass the grounding validator
(``response/grounding.py``) before it can replace the extractive answer
phrase. Every failure mode in this module returns ``None`` and the
caller falls back to the extractive pipeline — the LLM tier can only
ever *improve* an answer, never degrade or block one.

Uses stdlib urllib — no new dependency, no SDK. The API key arrives via
env (``HEXA_ANTHROPIC_API_KEY`` → ``settings.llm_api_key``) and is never
logged.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"

_SYSTEM_PROMPT = (
    "You are an answer synthesizer for a mortgage/loan knowledge base. "
    "You will receive a question and numbered evidence passages extracted "
    "verbatim from source documents.\n"
    "Rules:\n"
    "1. Use ONLY facts present in the evidence passages. Never add outside "
    "knowledge, numbers, or caveats.\n"
    "2. When using a fact from a passage, cite it inline as [1], [2] etc.\n"
    "3. If the passages do not fully answer the question, answer only the "
    "part they do cover.\n"
    "4. Be concise: 2-5 sentences, no preamble, no restating the question."
)


@dataclass
class SynthesisResult:
    text: str
    model: str


# Signals that a question needs the stronger (slower, pricier) model:
# explicit comparison, multi-part structure, or explanatory depth.
_COMPLEX_MARKERS = (
    "compare", "comparison", "difference", "different", "versus", " vs ",
    "why", "explain", "trade-off", "tradeoff", "pros and cons",
    "which is better", "walk me through", "step by step", "impact of",
)


def is_complex_question(question: str) -> bool:
    """Heuristic complexity router — Stage 2 of the integration plan.

    Deterministic, zero-cost, no LLM call. A question is 'complex' when
    it compares things, asks for explanation/causation, or carries many
    content words. Everything else routes to the fast model.
    """
    q = f" {question.lower().strip()} "
    if any(marker in q for marker in _COMPLEX_MARKERS):
        return True
    # Multi-part: several distinct asks in one message.
    if question.count("?") > 1 or ";" in question:
        return True
    # Length proxy: many CONTENT words (stop/question words removed) tend
    # to mean multiple constraints that need to be balanced together.
    from app.query_processing import domain_terms
    words = re.findall(r"[a-z']+", q)
    content = [
        w for w in words
        if w not in domain_terms.COMMON_WORDS
        and w not in domain_terms.QUESTION_STARTERS
        and w not in _COMPLEX_MARKERS
    ]
    return len(content) > 6


def _build_user_prompt(question: str, evidence: list[str]) -> str:
    passages = "\n\n".join(
        f"[{i}] {text}" for i, text in enumerate(evidence, start=1)
    )
    return f"Question: {question}\n\nEvidence passages:\n{passages}"


def synthesize(
    question: str,
    evidence: list[str],
    model: str | None = None,
) -> SynthesisResult | None:
    """Call Claude to synthesize a cited answer from retrieved evidence.

    ``model`` overrides the default (simple-tier) model — the search
    pipeline passes the complex-tier model for questions the router
    flags. Returns None on ANY failure — disabled, missing key, timeout,
    HTTP error, empty/malformed response — so the caller can fall back
    to the extractive answer without branching on error types.
    """
    if not settings.llm_enabled:
        return None
    if not settings.llm_api_key:
        logger.warning("llm_enabled is set but llm_api_key is empty; skipping synthesis")
        return None
    if not evidence:
        return None

    payload = json.dumps({
        "model": model or settings.llm_simple_model,
        "max_tokens": settings.llm_max_tokens,
        "system": _SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": _build_user_prompt(question, evidence)},
        ],
    }).encode("utf-8")

    request = urllib.request.Request(
        _API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": settings.llm_api_key,
            "anthropic-version": _API_VERSION,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request, timeout=settings.llm_timeout_ms / 1000
        ) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Never log the key; the response body may echo request details.
        logger.warning("LLM synthesis HTTP %d", exc.code)
        return None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("LLM synthesis failed: %s", exc)
        return None

    try:
        text = "".join(
            block["text"] for block in body["content"] if block.get("type") == "text"
        ).strip()
    except (KeyError, TypeError):
        logger.warning("LLM synthesis returned malformed content")
        return None

    if not text:
        return None
    return SynthesisResult(text=text, model=model or settings.llm_simple_model)
