# ADR-0001: HyDE is not adopted

**Status:** Rejected
**Date:** 2026-08-21
**Deciders:** Project owner + engineering agent
**Context:** "Modern RAG stack" wishlist review (ENGINEERING_PLAN.md Phase 5)

## Context

The proposed stack overhaul included HyDE (Hypothetical Document
Embeddings): at query time, an LLM generates a plausible *answer-shaped*
document, which is embedded and used as the retrieval vector instead of
the raw question.

## Decision

HyDE is rejected outright. No compliant subset exists.

## Reasons

1. **Violates the core guarantee.** CLAUDE.md's non-negotiable design
   philosophy is "find the right information, don't generate new
   information" — no generative LLM anywhere in the request-serving path.
   HyDE's entire mechanism *is* generation in the serving path. Every
   answer in Hexta must be verbatim source text so it can be traced to a
   source; HyDE puts synthesized text one step away from the user's answer.
2. **New standing dependency.** It requires an always-available LLM API,
   contradicting the socket-activated, memory-capped shared-host model
   (CLAUDE.md rules 4, 10).
3. **No evidence of need.** The Aug-2026 retrieval audit (RETRIEVAL_AUDIT.md)
   showed the recall problems HyDE targets were actually chunking/spell-
   correction defects — fixed narrowly with 61.5% → 98.1% on the regression
   matrix. The remaining known failure (fresh-data questions like "today's
   mortgage interest rate") is an answerability problem, not a query-shape
   problem HyDE would fix.

## Consequences

- Multi-Query and Step-Back remain the compliant ways to improve
  query↔document vocabulary mismatch (deterministic transforms only).
- If the no-generation philosophy is ever explicitly overturned, this ADR
  must be superseded, the compliance documentation rewritten, and a
  benchmark run must show net improvement before any LLM enters the path.

## Alternatives considered

- **Deterministic query variants** — adopted (Phase 5, Multi-Query row).
- **Doc2Query-style expansion at ingestion time** — legal under rule 5
  (batch-only), but adds generated text into the index that answers must
  then be traced against; deferred until a demonstrated recall gap.
