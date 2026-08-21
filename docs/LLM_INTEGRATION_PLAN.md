# LLM Integration Plan — Contingency Build

**Status:** NOT ACTIVE. Deferred contingency — build only if the current
retrieval-only pipeline demonstrably fails to answer questions it should.
**Date:** 2026-08-21
**Supersedes nothing; amends CLAUDE.md only upon adoption (see §6).**

---

## 0. Trigger conditions — when this plan activates

Adopt ONLY after all of the following hold, measured over a real usage
period:

1. `evaluation/run_benchmark.py` and the answer-level regression matrix
   stay at current levels (hit_rate@10 ≥ 92%, ndcg@10 ≥ 90%) yet users
   still reject answers via thumbs-down at a significant rate **with the
   failure reason being phrasing/synthesis quality** — not retrieval
   misses (those are `knowledge_gaps` / ranking work, not an LLM problem).
2. The audit's known top-1 ranking failures are fixed or quantified as
   irreducible with the current ~80MB cross-encoder.
3. A side-by-side prototype (§3) shows higher answer acceptance than the
   extractive baseline on the same query set.

If retrieval is the bottleneck, fix retrieval first. An LLM cannot
answer from evidence that was never retrieved.

---

## 1. Architecture (target state)

```
USERS
  ↓
Next.js Static Export (unchanged)
  ↓ HTTPS
FastAPI Backend (JWT / RBAC / validation / audit middleware)
  ↓
Response Cache (Postgres-native — NO Redis, see §2)
  ├─ exact-query hit → validated cached response
  └─ miss
        ↓
Query Processing (unchanged: spell → normalize → intent → entities
                 → split → expand)
        ↓
PostgreSQL Hybrid Search (Multi-Query + BM25 + pgvector + entity channel,
                          RBAC/version in WHERE — unchanged)
        ↓
RRF → ONNX Int8 Cross-Encoder → Top 3–5 evidence
        ↓
Complexity Router ──► LLM Synthesis Tier (feature-flagged)
        ↓                    ├─ SIMPLE → Haiku-class
Grounding Validator          └─ COMPLEX → Sonnet-class
  ├─ PASS (every claim entailed by evidence) → Citation Builder
  ├─ FAIL → one retry with stricter prompt → still FAIL
  │          → FALL BACK to extractive answer_phrase (current behaviour)
  └─ NO LLM AVAILABLE (flag off / API down / timeout) → extractive path
        ↓
Permission + Version Re-check (response/validation.py safety net)
        ↓
Response Packaging (+ provenance: which sentences are verbatim vs synthesized)
        ↓
Audit Logger (records llm_used, model, grounding verdict, cache status)
        ↓
Cache validated response (exact + semantic keys, version-stamped)
```

Non-negotiables within the target state:
- The extractive path remains the **default and fallback**. The system
  must be fully functional with `HEXA_LLM_ENABLED=false`.
- No generated sentence reaches the user without passing the grounding
  validator against retrieved evidence AND carrying citations.
- RBAC is enforced in SQL before retrieval (rule 1) and re-checked after
  generation — an LLM must never see evidence the user couldn't see, and
  its output is re-validated like any other package.

---

## 2. Caching — Postgres-native, no Redis

Redis stays banned (CLAUDE.md rule 2). All four cache layers map onto
the existing single Postgres instance:

| Layer | Implementation |
|---|---|
| Exact query cache | `response_cache` table, key = SHA256(normalized query + user scope class) |
| Semantic cache | `query_embedding vector(768)` column on `response_cache`; hit = cosine ≥ threshold (calibrate; start 0.97) |
| Version-aware invalidation | Store `document_ids[] + max(document.version)` per entry; any re-ingestion/approval change bumps versions → entry self-invalidates |
| Session/state | Already covered (`user_settings`, client-side history) |

Scope-class in the key prevents cross-user leakage: cache keys must
include the RBAC scope fingerprint (role + allowed_departments +
client_id), never user_id alone — two users with identical scope may
share an entry; different scopes must never.

Idempotent DDL in `db/postgres/schema.py` per project convention.

---

## 3. Staged build order

### Stage 0 — Response cache (no constraints touched; can build anytime)
Effort ~1 day. Pure latency/cost win, zero compliance impact. Ship even
if the LLM tier never happens.

### Stage 1 — Haiku-only synthesis behind a feature flag
Effort ~3–4 days.
- `HEXA_LLM_ENABLED=false` by default; `HEXA_LLM_MODEL` config.
- New `app/response/llm_synthesis.py`: prompt = question + top 3–5
  evidence chunks + strict instruction ("use ONLY these passages; cite
  chunk ids; say INSUFFICIENT_EVIDENCE if they don't answer").
- Grounding validator `app/response/grounding.py`: claim-level check —
  every factual sentence in the output must be entailed by ≥1 cited
  chunk (start lexical/NLI-lite; consider a small entailment model only
  if memory budget allows).
- Timeout budget: 1500ms p95 for the LLM call; on timeout/error →
  extractive fallback. Reranker budget (rule 6) unaffected.
- Audit log gains fields: `llm_used`, `llm_model`, `grounding_verdict`,
  `cache_hit`.
- Frontend: responses carry a `synthesized: true` marker so the UI can
  label non-verbatim answers.

### Stage 2 — Complexity router + second tier
Only if Stage 1's benchmark proves out. Heuristic router (question
length, multi-part detection, comparison flag — all already computed in
query processing) picks Haiku vs Sonnet-class. Never route client data
questions to any external API regardless of tier.

### Secrets & ops
- `HEXA_ANTHROPIC_API_KEY` injected via systemd `EnvironmentFile` /
  GH secret — never committed, never in compose defaults.
- Per-day spend cap + alert; hard circuit-breaker that flips
  `HEXA_LLM_ENABLED` off automatically if error rate or spend exceeds
  limits.
- Anthropic SDK added to requirements; outbound HTTPS only, no new
  inbound surface.

---

## 4. Evaluation requirements (before enabling anywhere)

Extend `evaluation/run_benchmark.py` with:
- **Faithfulness metric**: % of generated sentences entailed by cited
  evidence (the grounding validator's own verdict, reported separately
  from pass/fail gating).
- **Answer acceptance A/B**: extractive vs synthesized on the same seed
  corpus + a human-rated sample.
- Latency p50/p95 per mode; cache hit rate; $/query.
Record reports in `evaluation/reports/` per CLAUDE.md rule 7.

---

## 5. Explicitly out of scope forever

- HyDE / query-time hypothetical documents (ADR-0001) — even with an
  API key present, this stays rejected.
- LLM-generated text presented as verbatim source (provenance labels
  are mandatory).
- Any path where grounding validation fails open (fail = extractive
  fallback, always).

---

## 6. CLAUDE.md amendment required on adoption

Replace the blanket no-LLM philosophy with:
> No ungoverned generative LLM call in the serving path. LLM synthesis
> is permitted only behind `HEXA_LLM_ENABLED`, gated by the grounding
> validator, with automatic fallback to the extractive pipeline, full
> audit logging, and provenance labelling.

Rules 1–11 otherwise unchanged; rule 2 (no Redis) unchanged — caching
is Postgres-native per §2.
