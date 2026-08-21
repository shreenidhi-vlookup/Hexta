# HeXta — Final Project Summary

> This document is the canonical, non-normative description of the HeXta product, access model, architecture, data model, security rules, and UX. It is a living single-source-of-truth for anyone working on or extending HeXta.

---

## 1. What HeXta Is

HeXta is a **dual-audience Knowledge & Process Assistant**.

* **Primary audience — internal staff / process users.**
  HeXta removes the repetitive work staff do to gather information that lives across people, departments, documents, cases, and systems. Instead of "ask a client for info we already have," "ask another department," or "search documents by hand," staff ask a natural-language question and get a consolidated, sourced answer scoped to their authorization.
* **Secondary audience — authenticated clients.**
  Clients get secure, self-service access to **their own** documents, properties, mortgage/cases, application status, requirements, missing information, and end-to-end process progress.

HeXta is **retrieval-based at query time** — there is **no LLM in the serving path** and no generative answer construction. Answers are *extracted* from document chunks retrieved via hybrid search (BM25 + pgvector), fused with Reciprocal Rank Fusion and optional cross-encoder reranking, and packaged with confidence + routing labels. If the knowledge base does not contain a reliable answer (or the user is not authorized), HeXta returns a safe **no-answer** response and does **not** fabricate.

---

## 2. How HeXta Works (High-Level Flow)

```text
User Question
      ↓
Authentication           (JWT: role, department, client_id, allowed scopes)
      ↓
Authorization
  ├─ Identify user type   (staff vs client)
  ├─ Resolve access scope  (role/dept + assigned clients/cases/properties)
  └─ Build metadata/security filters  (BEFORE retrieval)
      ↓
Hybrid Search
  ├─ BM25 (keyword)        ─┐
  └─ pgvector (embedding)  ─┤ → RRF rank fusion → optional cross-encoder rerank
      ↓
Authorized chunks only     (is_active AND is_approved AND within scope)
      ↓
Response Package
  ├─ answer_phrase        (single extracted sentence, Sumy LSA at query time)
  ├─ excerpts             (source chunks, truncated, sourced)
  ├─ confidence           (0–100, from RRF)
  ├─ routing              (answer | partial | no_answer)
  └─ related_questions    (follow-ups)
      ↓
Frontend (ChatGPT-style UX)
```

Key invariants:
* Authorization is applied **before** retrieval and **before** any context reaches the LLM.
* Unapproved documents (`is_approved = false`) and inactive documents/chunks are **excluded** from retrieval.
* Confidence routing: ≥90 `answer`, 75–89 / 50–74 `partial`, <50 `no_answer`.

---

## 3. Architecture

```text
Documents
  → Chunking (structural_chunker.py)
  → Extractive LSA summary (Sumy, query-time + batch ingestion)
  → Embeddings (nomic-ai/nomic-embed-text-v1.5-Q ONNX Int8, 768-dim)
  → PostgreSQL + pgvector
  → Security-filtered hybrid search (BM25 [rank_bm25] + vector [pgvector HNSW], single SQL)
  → RRF rank fusion
  → Optional cross-encoder rerank (disabled by default)
  → Response builder (answer_phrase + excerpts + confidence + routing)
  → Frontend (Next.js 14 App Router, shadcn/ui, Tailwind)

Containers  : Docker (python:3.11-slim backend, nginx:alpine frontend)
Orchestration: docker-compose
Auth        : JWT (bcrypt + passlib)
```

### Layers at a glance

| Layer | Technology | Notes |
|-------|-----------|-------|
| Frontend | Next.js 14, React 18, TypeScript | static export behind nginx |
| UI kit | shadcn/ui, Tailwind | Radix primitives |
| Backend | FastAPI, Python 3.11 | single worker (`--workers 1`) |
| DB | PostgreSQL + pgvector | one Postgres per host |
| Embeddings | BGE-small ONNX quantized | |
| Search | BM25 + HNSW cosine | one fused SQL query |
| Auth | JWT | `HEXA_JWT_SECRET`, token in browser localStorage |
| Rerank | cross-encoder (optional) | off by default |
| Summarize | Sumy LSA | query-time answer_phrase + batch summaries |
| Upload | `/documents/upload` | 12 formats incl. OCR fallback for scans |

---

## 4. The Correct Access Model (DEPARTMENT ≠ CLIENT)

> **Do not model `Client = Department`.** They are separate concepts.

```text
                         HeXta
                           │
                Authentication (JWT)
                           │
             ┌─────────────┴─────────────┐
             │                       INTERNAL STAFF            │
             │              (role + dept + assigned scope)     │
             │                                                 │
             │        Role → Department → Assigned clients/cases │
             │                           │                      │
             └─────────────┬─────────────┘                      │
                           │                                    │
                     Authorization                            CLIENTS
                           │              EXTERNAL CLIENT      (client_id)
                           │  (own property/case/docs only)       │
                           └─────────────┬────────────────────────┘
                                         │
                              Resolve access scope
                                         │
                              Metadata/security filters  (BEFORE retrieval)
                                         │
                                Hybrid Search
                                         │
                              Authorized chunks only
                                         │
                                    RAG / answer package
                                         │
                                       Answer
```

### Staff authorization
```text
User → Role → Department → Assigned clients/cases → Permitted data → Search
```

### Client authorization
```text
Client identity → client_id → Owned/authorized properties → Cases → Documents → Search
```

---

## 5. Roles & Permissions

| Role | Access |
|------|--------|
| `super_admin` | Full system + admin + upload + approve + manage users (incl. promote) |
| `admin` | Admin panel + document management; upload + approve; **cannot** change roles |
| `loan_officer` | Assigned clients/cases + role-permitted info |
| `underwriter` | Assigned underwriting cases |
| `compliance` | Assigned compliance cases |
| other staff | Role + assigned scope; **no admin panel, no upload** |
| `client` | Own client/property/case/documents only |

`ADMIN_ROLES = {super_admin, admin}` — used for admin-panel gating and upload/approve.

Permission matrix (target):

| Action | admin | super_admin | staff | client |
|--------|------:|-----------:|------:|-------:|
| Upload | ✅ | ✅ | ❌ | ❌ |
| Approve | ✅ | ✅ | ❌ | ❌ |
| View permitted docs | ✅ | ✅ | ✅ | own only |
| Manage users | limited | full | ❌ | ❌ |

---

## 6. Data Model (Target Shape)

### Documents should carry business context
```text
Document
├── document_id
├── client_id      (nullable)
├── property_id    (nullable)
├── case_id        (nullable)
├── department
├── document_type
├── uploaded_by
├── is_approved    (default false after upload)
└── is_active
```

Example: `BankStatement.pdf` → `client_id: C001, case_id: CASE001, property_id: P001, department: mortgage, document_type: financial`

Relationship graph (what HeXta can consolidate per question):

```text
Client
├── Client information
├── Properties
├── Mortgage / Loan cases
├── Applications
├── Documents
├── Tasks
├── Status
├── Timeline
└── Related information
```

> Not every document needs every relationship, but the system must know **what the document belongs to** so it can scope retrieval and answer process questions.

---

## 7. Document Approval Workflow

```text
Admin/Super Admin
    ↓ Upload
 is_approved = false
    ↓ Search excludes it
Pending (visible only to approvers)
    ↓ Review
Admin/Super Admin Approve
    ↓
 is_approved = true
    ↓ Search includes it
Available to retrieval
```

* **Backend must enforce** `PATCH /documents/{id}/approve` (admin/super_admin only).
* Retrieval must exclude `is_approved = false` — **UI badge alone is insufficient**.
* Upload is admin-only (staff/clients do **not** upload).
* Current gap: ingestion defaults `is_approved = true`, so Documents always show "Approved." This is addressed by the approval workflow.

---

## 8. Critical Security Rule

**Never retrieve first and authorize later.** The authorization filter must happen **before** the retrieved content reaches the LLM/retrieval layer.

```text
Question → AuthN → user type → scope → metadata filters → hybrid search → authorized chunks → answer
```

Client A asking about Client B → resolved scope = Client B → not Client A → **no retrieval** → safe **no-answer** (without revealing whether Client B's information exists).

---

## 9. No Fabrication Policy

HeXta must **not** fabricate when:
* The information does not exist.
* The user is not authorized.
* Knowledge base is insufficient.
* Retrieval confidence is insufficient.

Response:
> "I couldn't find enough information in the available knowledge base to answer this accurately." (+ relevant follow-ups where appropriate).

---

## 10. UX / UI Definition

### Main chatbot (ChatGPT-style)
```text
┌─────────────────────────────────────────────────────────┐
│ HeXta                                   Settings  Sign out│
├─────────────────────────────────────────────────────────┤
│                      Conversation (centered ~900–1000px)│
│  User question                                          │
│  HeXta answer                                           │
│                                                         │
│  Copy   👍   👎   ↻                                      │
│  Related questions                                     │
└─────────────────────────────────────────────────────────┘
          [Ask about requirements... (multi-line composer)]
```
* Multi-line composer. `Enter` → send, `Shift+Enter` → newline. Send disabled when empty. Compose stays accessible while scrolling.
* Related questions appear **only for the latest message**; clicking creates a new user question in the conversation.
* Answer actions (Copy / Like / Dislike / Regenerate) kept subtle.
* Timestamp on assistant message goes to the **left** (next to avatar). Sources hidden behind a 3-dot/menu "View sources".

### Sidebar
* **Normal chat:** `+ New Chat`, `Recent` (local 24h TTL), `Settings`, `Help`. **No admin nav here.** The duplicate `Home` row is removed (keep only `+ New Chat`).
* **Admin:** separate admin dashboard (`Dashboard`, `Users`, `Documents`, `Audit Log`, `Feedback`, `Knowledge Gaps`) with a clear `← Back to Chat`.

### Empty state
Centered: "How can I help you today?" + suggested prompts (`Required documents`, `Eligibility`, `Application process`, `Mortgage status`). Same frame for staff and client — scope governs results.

### Upload placement
Upload button lives on the **Documents admin page** (not in chat). Documents table shows `is_approved` status + Approve action for permitted roles.

---

## 11. Conversation Retention

* **Live chat:** session-controlled; cleared only on `+ New Chat` or sign-out. Never auto-clear mid-flow.
* **Recent history:** `localStorage`, **24h TTL**, capped at 30 entries.
* **Server persistence:** **off by default**. The conversation module (`lib/conversations.ts`) is isolated so server persistence can be swapped in later (future optional `Settings → Chat history retention` of 1/7/30 days).

---

## 12. Current Minor Findings (from audit)

1. Duplicate `Home` nav row — remove; keep `+ New Chat`.
2. Documents always show "Approved" — fixed by approval workflow.
3. `AdminSections` fetches all 6 admin endpoints on open — acceptable; lazy-load per section is a future perf optimization.
4. `UploadForm` `accept` has a duplicate `.xlsx` — cosmetic fix.
5. "Recent" restore uses `now()` for timestamp (turns store no time) — acceptable for local history.
6. Expired-token handling: 401 should clear auth and redirect to login; 403 → Access Denied. Currently no hard redirect.

Test artifact: local dev user `admin2@hexa.local` (id 3) was created/reset during testing and is **not** in seed data.

---

## 13. Verification Targets

AuthN/AuthZ:
* `/admin` → admin allowed; staff/client → 403; expired token → 401 → login.
Upload: admin/super_admin allowed; staff/client → 403.
Approval: new doc = Pending; admin/super_admin Approve allowed; staff/client → 403.
Retrieval: staff see permitted client/case data; client sees own data only; client A cannot retrieve client B; unapproved docs not retrieved.
UI: ChatGPT-style layout; `Home` removed; `+ New Chat` works; Related Questions create new question; composer correct; admin nav separate.

---

## 14. Non-Goals (Initial Deployment)

* No LLM/generative answering in the serving path.
* No server-side conversation persistence by default (local 24h TTL).
* Department RBAC retained as one authorization layer (not replaced by client model).
* Staff do not upload (admin/upload/approve are admin/super_admin only).

---

## 15. Canonical Product Definition (Use this as the requirement statement)

> **HeXta is a dual-audience Knowledge and Process Assistant, primarily designed to improve internal staff/process efficiency while also providing authenticated clients with secure self-service access to their own documents, properties, mortgage/cases, status, requirements, and end-to-end process information.**
>
> **Internal staff access is controlled through role, department, and assigned client/case scope. External clients access only information belonging to or authorized for their own client identity. Departments and clients are separate concepts.**
>
> **The same knowledge and retrieval platform serves both audiences, but authorization determines what each user can retrieve. Authorization must be applied before retrieval and before any context reaches the LLM.**
>
> **New documents should enter a Pending state and become retrievable only after approval by an admin or super_admin.**
>
> **The main chatbot should use a clean ChatGPT-style conversational UX, while the admin interface remains a separate management dashboard.**
>
> **The initial deployment should remain lightweight: local 24-hour chat history, no server-side conversation persistence by default, existing department RBAC retained, and client/case/property scoping introduced without unnecessarily redesigning the existing system.**

### Key architectural distinction
```text
DEPARTMENT ≠ CLIENT
Department  → organizational/work area
Role        → what the user is allowed to do
Client      → whose business information is involved
Case        → which process/application is being handled
Property    → which property the information belongs to
Authorization scope → what this specific user is allowed to access
Document    → evidence/information connected to those entities
```
