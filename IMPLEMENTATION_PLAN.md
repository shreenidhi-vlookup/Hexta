# HeXta — Implementation Plan

Companion to `FINAL_PROJECT_SUMMARY.md`. This plan is **order-of-attack only**, not a guarantee of exact file paths or commits. **No existing code will be edited without explicit confirmation** — each phase below is proposed for Build Mode approval.

Reference tag for this session: **`HEXA-P-20260806-08-PARTIAL`**.

---

## 0. Status right now

* **Plan Mode** through this write-up. The two docs above (`FINAL_PROJECT_SUMMARY.md`, `IMPLEMENTATION_PLAN.md`) are new, standalone documentation — **no code was changed in this session.**
* The repo has **no new commits** from this session (read-only Plan Mode).
* A local dev test user `admin2@hexa.local` (id 3) exists in the dev DB only — **not** in seed data.

---

## How we map spec → work

The summary defines the target. This plan breaks the gap between "current running system" and "target" into phases. Each phase lists: what it touches, why, and the single most important acceptance check.

| Summary § | Plan Phase |
|-----------|------------|
| §6 Data model | Phase 1 (schema) |
| §7 Approval | Phase 2 (approval) |
| §4 Access model / §5 Roles | Phase 3 (scoping) |
| §7 Security rule | Phase 4 (pre-filter) |
| §10 UX | Phase 5 (UI) |
| §12 Findings | Phase 6 (polish) |
| §11 Retention | Phase 7 (optional) |

---

## Phase 1 — Document business context (schema + ingestion)

**Goal:** documents know *what they belong to* (client/case/property) so retrieval can scope by owner, not just department.

**Do** (additive, idempotent DDL per `schema.py` conventions):
* Add nullable foreign-key-style columns to `documents`: `client_id`, `property_id`, `case_id` (text/uuid per existing PK style), `document_type` (text), `uploaded_by` (int→users). Keep backward compatible — nullable.
* Add matching context columns to `document_chunks` (`client_id`, `property_id`, `case_id`, `document_type`) for efficient filtering, populated from the document row at chunk time. Add a composite index `idx_chunks_scope` on `(department, client_id, document_type, is_active, is_approved)`.
* Update `structural_chunker.py` / ingest to populate chunk-level context from the source document row.
* Add `client_id`/`property_id`/`case_id`/`document_type` to the upload response so the caller can attach an uploaded doc to business context (or mark `is_approved=false` and route to approval).

**Acceptance:** `psql` shows new nullable columns on `documents` and `document_chunks`; re-ingest populates them; search filters still work.

---

## Phase 2 — Approval workflow (backend-first, the critical correctness fix)

**Goal:** new documents are **Pending** and not retrievable until approved by admin/super_admin.

**Why first:** §7 and §8 make this mandatory — an unapproved doc must be excluded at retrieval regardless of the UI badge.

**Do:**
* Change ingestion/upload default: new `documents.is_approved := false` (was effectively `true`).
* Add `PATCH /documents/{id}/approve` (`is_approved=true`) — `require_role(user, "admin")` (admin + super_admin).
* Add `PATCH /documents/{id}` to flip `is_active` (archive), admin-only.
* **Critical:** ensure `search.py` hybrid query excludes `is_approved = false` AND `is_active = false` (metadata filter `document_chunks.is_active AND document_chunks.is_approved`). Verify `document_chunks.is_approved` is joined/wired from `documents.is_approved`.
* Documents admin table: show `Pending` badge; add Approve/Deactivate actions for permitted roles.

**Acceptance (security test):** upload as admin → `is_approved=false` → ask the unapproved doc's content → `no_answer`. Then Approve → same question → `answer`. (Automated in integration test.)

---

## Phase 3 — Dual-audience authorization scope (Phase 3a) & staff scope (3b)

### 3a. Client user type
**Goal:** clients resolve to their own scope only.
* Introduce `client_id` on `users` (nullable) — `role='client'`.
* Authorization: for a client, scope = `{ client_id }` (own docs/properties/cases). Add `user_claims` resolver returning `user_type`, `allowed_clients`, `allowed_departments`, `role`.
* Staff keep existing `allowed_departments` as **one** layer; optionally add `assigned_clients`/`assigned_cases` to `users` (Phase 3b) — do not remove department RBAC.
* Search metadata filter becomes: `department IN allowed_departments AND (client_id IN allowed_clients OR client_id IS NULL)` for staff; `= own client_id` for clients.

### 3b. Staff assigned scope (optional follow-up to 3a)
* Add `assigned_clients`/`assigned_cases` arrays to `users` (or a `user_scopes` table).
* Wire into filters once data exists.

**Acceptance:** client A logs in → can see own docs; client B docs never returned; staff see their assigned scope; no cross-client leakage (automated isolation test).

---

## Phase 4 — Enforce pre-retrieval filtering (security hardening)

**Goal:** authorization happens **before** retrieval, never after.
* Centralize scope resolution in `search.py` (or a `authorization.py` scope builder): build the SQL `WHERE`/metadata-filters from the resolved user claims **before** any embedding/lattice access.
* Drop any code path that retrieves without filters for authenticated users.
* Add a regression test: `client A` query that names `client B` content → returns `no_answer`, and audit log records `no retrieval` (no chunk ids for B).

---

## Phase 5 — UX polish (ChatGPT-style main + clean admin separation)

**Goal:** §10 — clean chat, no duplicate `Home`, admin separate.
* Main chat: centered ~900–1000px, document-oriented layout, multi-line composer (`Enter` send / `Shift+Enter` newline, send disabled when empty), Related Questions only under latest message (click = new user question), answer actions subtle, timestamp left, sources behind 3-dot "View sources".
* Sidebar: remove duplicate `Home`; keep `+ New Chat`, `Recent` (24h local), `Settings`, `Help`. Admin items hidden from non-admins.
* Admin: keep `/admin` dashboard; add `← Back to chat`; place Upload Document on the **Documents** page (not chat); show Approve/Deactivate per row.
* Empty state: "How can I help you today?" + suggested prompts (`Required documents`, `Eligibility`, `Application process`, `Mortgage status`).
* Expired token: 401 → clear auth → redirect to `/login`; 403 → Access Denied toast.

**Acceptance:** tsc + eslint + build pass; visual checks match the mock.

---

## Phase 6 — Minor findings cleanup

* Remove duplicate `Home` nav item (HomeSidebar `CHAT_ITEMS`).
* Fix `UploadForm` `accept` duplicate `.xlsx`.
* "Recent" restore shows `now()` (turns have no timestamp) — acceptable; defer if desired.
* `AdminSections` fetches all endpoints up-front — keep (lazy-load only if perf warrants).

---

## Phase 7 — Conversation retention (optional, deferred to later)

* Initial: local 24h TTL (already implemented in `lib/conversations.ts`), no server persistence.
* Future (optional): `user_settings.history_ttl_days` (1/7/30) + server `recent_chats` table swap. **Off unless requested.**

---

## Phase 8 — Verification & hardening

Run (per repo `AGENTS.md`):
```
tsc --noEmit ; eslint . ; (frontend build)
pytest tests/unit/ -v --timeout=60
pytest tests/integration/ -v --timeout=120   (Postgres)
```
Add/expand integration tests for the security matrix:
* auth: admin allowed, staff/client → 403 on admin, expired → 401.
* upload: admin/super_admin only; staff/client → 403.
* approval: unapproved not retrieved; approved retrieved.
* retrieval isolation: client A cannot read client B; staff only within scope; unapproved excluded.
* UI: `/admin` for non-admin → 403/redirect; `/admin` route not exposed to normal chat nav; `Home` removed.

---

## Open decisions required before any code changes

These map directly to the summary. I will **not** build until you confirm:

1. **Clients vs departments (Q1)** — ✅ confirmed separately: clients are a **real entity** (`client` role + `client_id` → own docs/props/cases). Staff keep department RBAC as a layer. **Confirm 3a/3b scope.**
2. **Approval (Q2)** — new docs `is_approved=false`; who can upload/approve? `admin` + `super_admin` only (my default). Staff/clients never upload. **Confirm.**
3. **Staff assigned scope** — add `assigned_clients`/`assigned_cases` (Phase 3b) or keep department RBAC only for now?
4. **Server persistence** — keep local 24h TTL only (no server history) for initial deployment?
5. **Admin nav location** — keep admin in `/admin` (separate route) as written in §10? (Yes — the new home-sidebar admin group is only for the chat app's *user* settings, not document/admin management.)

---

## Build gates / safety

* **No LLM in serving path** (summary §4 / decision #1 of the project) is a hard constraint — do not add LLM answering.
* **No fabrication** — `no_answer` on low confidence or out-of-scope.
* **Pre-retrieval filtering** is non-negotiable for client isolation.
* **Approval enforced in backend**, not just UI.
* All schema changes are idempotent DDL in `backend/app/db/postgres/schema.py` (per project convention).

---

## Next step

Reply with your confirmations on the 5 open decisions above, then say **"build"** — I will start Phase 1 → Phase 8 in order, with verification at the end of each phase, and stop for sign-off between phases unless you say to proceed straight through.
