# Engineering Plan — Next Steps for Hexta

**Date:** 2026-08-11  
**Branch:** `audit/chatbot-e2e`  
**Context:** Session 8 complete (answer-quality Phases A/B/C + spell + splitter). All 240 unit tests pass. Frontend build green. Integration client-isolation tests skipped due to host port shadowing. Staged (55 files) + unstaged (8 files) work uncommitted.

---

## Phase 1: Unblock Integration Tests (Immediate, <1h)

**Goal:** Run `tests/integration/test_client_isolation.py` green locally to validate the dual-audience RBAC scoping end-to-end.

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | Change docker-compose.yml: postgres published port `5432` → `55432` (avoids Windows native Postgres shadowing) | `docker compose up -d` shows postgres on 55432 |
| 1.2 | Set `HEXA_DATABASE_URL=postgresql://hexa_app:devpass@127.0.0.1:55432/hexa_assistant` in shell | Connection succeeds from host venv |
| 1.3 | Run integration suite: `cd backend && $env:PYTHONPATH=".." && python -m pytest tests/integration/ -v --timeout=120` | **18/18 pass** (includes client-isolation) |
| 1.4 | Revert docker-compose.yml port change (or keep 55432 as documented convention per AGENTS.md) | Clean state or documented local port |

**Decision point:** If 1.3 passes → proceed to Phase 2. If blocked → accept unit-level coverage (test_rbac_prefilter passes) and move on.

---

## Phase 2: CI Regression Gate (30 min)

**Goal:** Hard-fail PRs if retrieval quality regresses.

| Step | Action | File |
|------|--------|------|
| 2.1 | Add threshold constants to `eval_on_pr.yml` regression step (e.g. `hit_rate@10 >= 85%`, `MRR >= 0.7`, `nDCG@10 >= 0.8`) | `.github/workflows/eval_on_pr.yml` |
| 2.2 | Make regression step `fail` on threshold breach (currently only logs) | `.github/workflows/eval_on_pr.yml` |
| 2.3 | Verify locally: `cd repo-root && python -m evaluation.run_benchmark --output-dir evaluation/reports` meets thresholds | Benchmark run |

---

## Phase 3: Commit & Push (5 min)

**Goal:** Land all Session 7+8 work.

| Step | Action |
|------|--------|
| 3.1 | `git add -A` (stages both staged dual-audience refactor + unstaged A/B/C + spell + splitter) |
| 3.2 | `git commit -m "refactor: dual-audience access + answer-quality Phases A/B/C + spell + splitter"` |
| 3.3 | `git push origin audit/chatbot-e2e` |

---

## Phase 4: Production Hardening (Post-merge, parallelizable)

| # | Item | Effort | Priority |
|---|------|--------|----------|
| 4.1 | User registration + password reset flow | 4–8h | High |
| 4.2 | Rate limiting + brute-force lockout on `/login` | 2h | High |
| 4.3 | `answer_phrase` → true extractive summary (Sumy at query time over top-k) | 4h | Medium |
| 4.4 | Server chat persistence (deferred Phase 7) | 8–12h | Medium |
| 4.5 | Idempotent re-ingestion (versioned `is_active` toggle) | 3h | Medium |
| 4.6 | Expose chunk `summary` in API / 3-dot menu | 1h | Low |
| 4.7 | Observability: response latency + confidence distribution metrics | 3h | Medium |
| 4.8 | Secrets: ensure `HEXA_JWT_SECRET` injected via env in systemd units | 1h | High |
| 4.9 | Align Docker dev flow ↔ shared-host systemd runbook | 2h | Low |
| 4.10 | ~~Re-derive production memory budgets for nomic swap~~ **DONE** — measured peak RSS ~275MB; `hexa-backend.service` `MemoryMax` 200M→400M, ingestion runbook documents ~600MB transient, CLAUDE.md rule 10 rewritten, dev compose at 1g | 2h | **High** |

---

## Phase 5: Constraint-Compliant Adoption of the "Modern RAG Stack" Wishlist

The proposed stack overhaul — **GraphRAG, Self-RAG, HyDE/Multi-Query/
Step-Back, ColPali, Docling** — remains **deferred as agreed**: all three
bugs it was motivated by turned out to be ordinary, narrow correctness
issues in the existing architecture, not evidence that a stack swap was
needed. This section records the *parts* that can be adopted inside the
current architecture without violating CLAUDE.md (no LLM in the serving
path, no new containers/DBs per rules 1–3, batch-only heavy work per
rule 5). Everything below is additive and independently revertible.

| Stack item | Verdict | Constraint-compliant version (if any) |
|---|---|---|
| **Multi-Query** | ✅ **Implemented** | `generate_query_variants` in `query_expansion.py` emits up to 3 deterministic rewrites (original / alias-expanded / definition-subject). The orchestrator embeds each variant and admits/ranks chunks by **best similarity across variants** — still one SQL statement (`search/hybrid_orchestrator.py`). No generation, pure transforms. |
| **Self-RAG** | ✅ **Implemented** (subset) | Bounded self-critique without an LLM: `search.py::_build_block` makes **one** recovery retrieval with the alternate variant when the `answerability.py` veto fires, kept only if the top rerank score is better AND answerable. Hard cap 1 retry; no-op when reranking is disabled. |
| **Step-Back prompting** | ⚠️ Adoptable later | Rule-based generalization only (`"max LTV for investment properties?"` → step-back `"LTV guidelines"`) is compliant — the transform machinery now exists in `generate_query_variants`. Defer until benchmark shows Multi-Query leaves a residual gap it would close. |
| **Docling** | ⚠️ Adoptable (batch only) | A document-parsing library upgrade for `ingest_batch.py` / `text_extraction.py` / `ocr.py` is legal — rule 5 confines it to the batch path. But OCR + extraction currently passes its categories; adopt only if a real format regresses. Memory-capped host must be validated. |
| **GraphRAG** | ✅ **Adopted as GraphRAG-lite** | Entity graph *inside the existing Postgres*: `chunk_entity_links` table (chunk→canonical-entity edges harvested at ingestion by `documents/entity_extraction.py`), joined at query time as a third RRF channel in the same SQL statement (`search/hybrid_orchestrator.py`) — alias-insensitive, no graph store, no new container. `entity_weight` in `ranking/weights_config.py` is an untested 0.15 default: calibrate via benchmark before relying on it. |
| **HyDE** | ❌ Rejected — see `docs/adr/0001-hyde-not-adopted.md` | Requires a generative LLM in the serving path — violates the core no-generation guarantee outright. No compliant subset exists. |
| **ColPali** | ⏸ Deferred — see `docs/adr/0002-colpali-deferred.md` | Vision-language retrieval blows the memory caps and needs a second multi-vector index; revisit triggers documented in the ADR. |

Per CLAUDE.md rules 6–7, any adopted item touching ranking/packaging ships
with before/after `evaluation/run_benchmark.py` numbers recorded in
`evaluation/reports/`.

---

## Acceptance Criteria for This Plan

- [x] Phase 1: `tests/integration/` 18/18 pass locally (port 55432 convention per AGENTS.md)
- [x] Phase 2: `eval_on_pr.yml` fails on retrieval regression (absolute floors added: hit_rate@10≥0.85, MRR≥0.7, nDCG@10≥0.8)
- [x] Phase 3: All work committed and pushed to `audit/chatbot-e2e` (PR: https://github.com/shreenidhi-vlookup/Hexta/pull/new/audit/chatbot-e2e)
- [ ] Phase 4: Tracked as follow-up tickets (not blocking merge)

---

**Status:** Phases 1-3 **COMPLETE**. Phase 4 items are the production hardening backlog. Phase 5: GraphRAG-lite, Multi-Query, and the Self-RAG subset **implemented** (pending re-ingestion + benchmark calibration of `entity_weight` and reranker p95 re-check); Step-Back/Docling deferred with triggers; HyDE rejected and ColPali deferred per ADRs in `docs/adr/`.