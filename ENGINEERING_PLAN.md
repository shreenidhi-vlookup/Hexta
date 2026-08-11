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

---

## Acceptance Criteria for This Plan

- [ ] Phase 1: `tests/integration/` 18/18 pass locally (or documented skip with unit coverage justification)
- [ ] Phase 2: `eval_on_pr.yml` fails on retrieval regression (manual PR test)
- [ ] Phase 3: All work committed and pushed to `audit/chatbot-e2e`
- [ ] Phase 4: Tracked as follow-up tickets (not blocking merge)

---

**Next action (user):** Confirm Phase 1 approach (port-forward 55432) or accept skip → then I execute.