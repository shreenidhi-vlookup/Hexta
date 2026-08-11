# AGENTS.md — Project Knowledge Base

This file captures everything known about the Hexta project — architecture, stack, key files, decisions, and current state. It serves as a single reference for any agent working on this codebase.

---

## Project Overview

**Hexta** is a RAG-based Knowledge Assistant for loan requirements and regulations. Users ask natural-language questions and receive answers sourced from internal documents. The system uses hybrid search (BM25 + pgvector) to retrieve relevant document chunks and presents them as answer phrases with source traceability.

---

## Architecture

```text
Documents
  → Chunking (structural_chunker.py)
  → Extractive Summarization (sumy LSA, batch only)
  → Embeddings (BAAI/bge-small-en-v1.5, ONNX quantized)
  → PostgreSQL + pgvector
  → Hybrid Search (BM25 + Vector, single SQL query)
  → RRF Rank Fusion
  → Optional Cross-Encoder Reranking
  → Response Package (answer_phrase + excerpts + confidence + routing)
  → Frontend (Next.js 14, shadcn/ui)
```

---

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router), React 18, TypeScript |
| UI | shadcn/ui (Radix primitives), Tailwind CSS |
| Backend | FastAPI (Python 3.11) |
| Database | PostgreSQL + pgvector |
| Embeddings | BAAI/bge-small-en-v1.5 (ONNX, quantized) |
| Search | BM25 (rank_bm25) + pgvector hybrid |
| Reranking | Optional cross-encoder (disabled by default) |
| Summarization | sumy (LSA, batch ingestion only) |
| Auth | JWT (bcrypt + passlib) |
| Container | Docker (python:3.11-slim for backend, nginx:alpine for frontend) |
| Orchestration | docker-compose |

---

## Key Files

### Backend

| File | Purpose |
|------|---------|
| `backend/app/main.py` | FastAPI app entry point |
| `backend/app/config.py` | Settings from env vars (HEXA_ prefix) |
| `backend/app/db/postgres/schema.py` | Idempotent DDL — all tables defined here |
| `backend/app/db/postgres/session.py` | Connection pool management |
| `backend/app/api/v1/search.py` | Search endpoint — full retrieval pipeline |
| `backend/app/api/v1/settings.py` | User settings endpoints (GET/PUT) |
| `backend/app/api/v1/router.py` | API router aggregator |
| `backend/app/response/package_builder.py` | Builds ResponsePackage with answer_phrase + excerpts |
| `backend/app/response/confidence_thresholds.py` | `route_by_confidence()` — maps score to answer/partial/no_answer |
| `backend/app/response/validation.py` | Safety-net RBAC/version check |
| `backend/app/search/hybrid_orchestrator.py` | Combined BM25 + pgvector SQL query |
| `backend/app/ranking/rrf.py` | Reciprocal Rank Fusion |
| `backend/app/ranking/reranker.py` | Optional cross-encoder reranking |
| `backend/app/documents/summarization.py` | Extractive LSA summarization (batch only) |
| `backend/app/documents/ingest_batch.py` | Batch ingestion pipeline |
| `backend/app/documents/structural_chunker.py` | Structural chunking (tables, checklists, paragraphs) |
| `backend/app/documents/ocr.py` | OCR fallback for scanned PDFs |
| `backend/app/documents/entity_extraction.py` | Dictionary-based entity extraction |
| `backend/app/query_processing/pipeline.py` | Query processing (expansion, intent, entities) |
| `backend/app/query_processing/multi_question.py` | Splits compound queries into per-question sub-queries |
| `backend/app/query_processing/coreference.py` | Resolves pronouns/it to prior history topics |
| `backend/app/query_processing/comparison.py` | Detects comparisons and extracts the two operands |
| `backend/app/query_processing/alias_resolver.py` | Query-time acronym/alias expansion from `term_aliases` |
| `backend/app/documents/abbreviations.py` | Ingestion-time acronym harvest into `term_aliases` |
| `backend/app/auth/rbac.py` | RBAC scope resolver |
| `backend/app/auth/jwt_handler.py` | JWT encode/decode |
| `backend/app/audit/audit_logger.py` | Audit logging for every query |
| `backend/app/knowledge_gap/gap_detector.py` | Logs low-confidence / no-answer queries |

### Frontend

| File | Purpose |
|------|---------|
| `frontend/app/page.tsx` | Main chat page — all message rendering logic |
| `frontend/app/login/page.tsx` | Login page |
| `frontend/app/layout.tsx` | Root layout |
| `frontend/components/search/ResponsePackageCard.tsx` | Result card — embedded mode shows answer_phrase + 3-dot menu |
| `frontend/components/search/MultiAnswerCard.tsx` | Per-question result blocks for compound/comparison queries |
| `frontend/components/search/SourceCitation.tsx` | Compact source citation (standalone use) |
| `frontend/components/search/ConfidenceBadge.tsx` | Confidence/routing badge |
| `frontend/components/search/RelatedQuestions.tsx` | Accordion of follow-up questions |
| `frontend/components/search/SearchBar.tsx` | Search input with speech recognition |
| `frontend/components/settings/SettingsDialog.tsx` | Settings dialog with show_related_questions toggle |
| `frontend/components/ui/message.tsx` | Message bubble layout (user/assistant) |
| `frontend/components/ui/conversation.tsx` | Scrollable chat container |
| `frontend/components/ui/dropdown-menu.tsx` | Radix dropdown menu wrapper |
| `frontend/components/ui/dialog.tsx` | Radix dialog wrapper |
| `frontend/components/ui/card.tsx` | Card container |
| `frontend/components/ui/avatar.tsx` | Avatar with fallback initials |
| `frontend/components/ui/button.tsx` | Button component |
| `frontend/lib/api-client.ts` | Direct fetch API client + TypeScript interfaces |
| `frontend/lib/auth.ts` | JWT storage/retrieval |
| `frontend/lib/greetings.ts` | Canned replies for greetings/small talk |

---

## Database Schema

### Tables

| Table | Purpose |
|-------|---------|
| `users` | User accounts (email, password_hash, role, department, allowed_departments) |
| `documents` | Uploaded documents (title, source_path, doc_type, department, version) |
| `document_chunks` | Searchable chunks (content, embedding, summary, fts vector) |
| `audit_log` | Every query logged (user, query, retrieved_ids, confidence, response_id, outcome) |
| `feedback` | Thumbs up/down ratings per response |
| `knowledge_gaps` | Low-confidence / no-answer query signals |
| `user_settings` | Per-user UI preferences (show_related_questions) |
| `term_aliases` | Ingestion-harvested acronyms/aliases (alias UNIQUE → canonical) for query-time expansion |

### Key Indexes

- `idx_chunks_document` — on `document_chunks(document_id)`
- `idx_chunks_active` — on `document_chunks(department, is_active, is_approved)`
- `idx_chunks_fts` — GIN index on `document_chunks.fts` (full-text search)
- `idx_chunks_embedding` — HNSW index on `document_chunks.embedding` (vector cosine)
- `uq_chunks_content_hash` — UNIQUE index on `document_chunks.content_hash`

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/auth/login` | Authenticate, return JWT |
| POST | `/api/v1/auth/verify` | Verify JWT token |
| POST | `/api/v1/search` | Hybrid search — returns answer_phrase + excerpts + confidence + routing |
| GET | `/api/v1/settings` | Read user settings |
| PUT | `/api/v1/settings` | Update user settings |
| POST | `/api/v1/feedback` | Submit thumbs up/down feedback |
| POST | `/api/v1/documents/upload` | Upload document for ingestion |
| GET | `/api/v1/analytics` | Analytics dashboard data |
| GET | `/api/v1/admin/` | Admin endpoints |

---

## Confidence Routing

| Score Range | Routing | Meaning |
|-------------|---------|---------|
| ≥ 90 | `answer` | High confidence — show answer |
| 75–89 | `partial` | Partial answer — show with caveat |
| 50–74 | `partial` | Low confidence — show with caveat |
| < 50 | `no_answer` | No reliable answer found |

---

## ResponsePackage Structure

```python
@dataclass
class ResponsePackage:
    response_id: str
    title: str                    # Source document title
    answer_phrase: str            # Single extracted sentence from top chunk
    excerpts: list[Excerpt]       # Retrieved source chunks
    related_questions: list[str]  # Follow-up question suggestions
    confidence: float             # 0-100 score from RRF
    routing: str                  # "answer" | "partial" | "no_answer"
    max_excerpt_chars: int        # Truncation limit (default 600)
```

The `/api/v1/search` endpoint returns a `SearchResponse` that extends this: each sub-question of a compound query becomes its own block under `answers: list[AnswerBlock]` (each with `question`, `title`, `answer_phrase`, `excerpts`, `confidence`, `routing`). Top-level fields mirror the best block. `answered`/`total` report how many sub-questions were answered; `comparison` is true when the query was a comparison.

---

## UI/UX Patterns

### Chat Bubble Layout (Assistant Message)

```text
┌─────────────────────────────────────────┐
│ Answer phrase (single sentence)         │
│ 12:34                                   │
│ ⋮ More → View Sources                   │
└─────────────────────────────────────────┘

🔊 Speak   📋 Copy   ↻ Regenerate

👍 Like    👎 Dislike

Related Questions
• Question suggestion 1
• Question suggestion 2
```

### Source Details (Hidden by Default)

Accessible via 3-dot menu → "View sources (N)":
- Document title
- Section name
- Excerpt text

### No-Answer State

```text
No answer found
I could not find a reliable answer to this question in the available knowledge base.
```

---

## Key Decisions

1. **No LLM in serving path** — The system is retrieval-only at query time. No generative AI calls in the request path.
2. **Runtime extractive summarization allowed** — CLAUDE.md permits LexRank/TextRank/LSA via Sumy for producing answer phrases.
3. **No pre-computed summaries** — Summaries are computed at query time from retrieved chunks, not stored during ingestion.
4. **One Postgres per host, one DB per project** — No per-project containers.
5. **Backend runs with `--workers 1`** — Socket-activated, not meant to run continuously.
6. **BM25 is a search algorithm** — Not a summarization model. Used for keyword-based retrieval alongside vector search.
7. **Source details hidden by default** — Users must explicitly open the 3-dot menu to see where answers came from.
8. **User settings persist in Postgres** — `user_settings` table with per-user preferences.

---

## Sessions Summary

| Session | Phase | Key Changes |
|---------|-------|-------------|
| 1 | A, C, E | Bug fixes (gap_detector, search.py, migrate_db.sh), benchmark enhancement, integration tests |
| 2 | B, D | Dead code removal, NER decision (removed spaCy/GLiNER), documentation alignment |
| 3 | C/E fixes | Fixed benchmark CI bugs (ModuleNotFoundError, dict-row access, SQL syntax) |
| 4 | Container validation | Docker stack validated, OCR enabled, 12 file formats supported, friendly upload messages |
| 5 | Frontend polish | Greetings, voice input, 3-dot source menu, timestamps, Sumy batch integration |
| 6 | UI overhaul + settings | Answer phrase in chat bubble, sources hidden behind 3-dot menu, Speak/Copy/Regenerate actions, user settings toggle, no-answer state |
| 7 | Multi-question + context handling | Per-question answer blocks (search.py rewrite), coreference, comparison, scenarios, doc-derived abbreviations/aliases, settings 422 fix |

---

## Container Setup

### Development

```bash
docker compose up -d
```

Services:
- `hexa_postgres` — PostgreSQL + pgvector on port 5432
- `hexa_backend` — FastAPI on port 8001. **No code bind mount** — only `./storage:/app/storage` is mounted; code is baked into the image and uvicorn runs without `--reload`. Code changes require `docker compose up -d --build hexa-backend`.
- `hexa_frontend` — Next.js static export on port 80 (nginx)

### Production (shared host)

See `shared-host-infra-scaffold/` for systemd units and nginx config.

---

## Testing

```bash
# Unit tests (backend)
cd backend
$env:HEXA_JWT_SECRET="dev-only-secret-change-me-in-production-32chars"
$env:HEXA_ENVIRONMENT="test"
python -m pytest tests/unit/ -v --timeout=60

# Integration tests (requires Postgres)
cd backend
$env:PYTHONPATH="<repo-root>"
python -m pytest tests/integration/ -v --timeout=120

# Benchmark (requires Postgres, run from repo root)
$env:HEXA_DATABASE_URL="postgresql://hexa_app:devpass@127.0.0.1:5433/hexa_assistant"
python -m evaluation.run_benchmark --output-dir evaluation/reports
```

---

## Known Issues / Limitations

1. **No LLM in serving path** — Answers are extracted from chunks, not generated. If the KB doesn't have the answer, it returns "No answer found."
2. **answer_phrase is first sentence of top chunk** — Not a true summary. May be incomplete for complex questions.
3. **No user registration** — Users are seeded manually.
4. **Single admin password** — `HexaAdmin@123` for dev (reset via script inside container).
5. **Windows host Postgres shadowing** — Use port 5433/55432 for Docker testing on Windows hosts with native Postgres on 5432.
