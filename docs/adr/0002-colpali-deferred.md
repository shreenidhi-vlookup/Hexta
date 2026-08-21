# ADR-0002: ColPali is deferred

**Status:** Deferred (revisit triggers defined below)
**Date:** 2026-08-21
**Deciders:** Project owner + engineering agent
**Context:** "Modern RAG stack" wishlist review (ENGINEERING_PLAN.md Phase 5)

## Context

ColPali retrieves document pages by embedding page *images* with a
vision-language model (multi-vector, late-interaction scoring), skipping
text extraction entirely. Proposed as part of the "modern RAG stack"
overhaul for better handling of visually structured documents.

## Decision

Deferred. Not adopted now; revisit only if the triggers below fire.

## Reasons

1. **Memory caps.** ColPali-class vision models are hundreds of MB even
   quantized; the backend service is capped at 400M (CLAUDE.md rule 10,
   raised from 200M for the nomic embedding model, which alone peaks at
   ~275MB). There is no headroom for a second, larger vision model, let
   alone multi-vector page embeddings.
2. **Storage and schema.** Late-interaction retrieval needs ~100+ vectors
   per page, not one per chunk — a fundamentally different pgvector layout
   (MaxSim operators, different indexing), i.e. a second retrieval engine
   alongside the existing hybrid search.
3. **Ingestion cost.** Page-image rendering plus vision-model inference
   per page would multiply batch ingestion time and storage severalfold.
4. **No demonstrated defect.** The audit's OCR fallback already handles
   scanned PDFs, and structured-table retrieval measured 100% before and
   after (RETRIEVAL_AUDIT.md). ColPali solves a problem this corpus has
   not been shown to have.

## Revisit triggers

Adopt only if ALL of the following hold:
- Real documents arrive whose meaning lives in visual layout (charts,
  forms, stamps) AND text extraction measurably fails on them;
- The host memory budget is raised or the model can be confined to a
  separate batch-only indexing pass with serving staying text-only;
- An `evaluation/run_benchmark.py` A/B shows a net win over the current
  OCR + structural-chunking path.

## Alternatives considered

- **OCR fallback + structural chunking** — current path, passing its categories.
- **Row-level table indexing** (`table_chunker.py`) — cheaper first step if
  table retrieval ever regresses (audit's own recommendation).
