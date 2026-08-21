# Hexta — Knowledge-Based AI Assistant

A lightweight, retrieval-only AI assistant for compliance and document queries. **No LLM generation anywhere** — every response is a verbatim excerpt from retrieved documents. Designed for shared AWS EC2 micro-tier deployment (1 GiB RAM) where latency, compliance, and cost matter.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Quick Start (Development)](#quick-start-development)
- [Production Deployment](#production-deployment)
- [Testing](#testing)
- [Evaluation & Benchmarks](#evaluation--benchmarks)

---

## Architecture Overview

```
Browser → Nginx (30MB) → FastAPI (socket-activated, 400MB cap, idle-stops)
                                    │
                    ┌───────────────┼────────────────┐
                    ▼                ▼               ▼
           Query Processing     Hybrid Postgres      Audit Logger
           (pure, deterministic)   Query             (every query)
           normalize→spell-correct  BM25 + pgvector   user, query, docs, ts,
           →split→entity→intent→    RBAC in WHERE     confidence, response_id
           →expand                  clause

Document Ingestion (batch only — never in API path)
  Upload → Validate → Extract text → Chunk → Embed → Index to pgvector
```

### Key Architectural Constraints

| Constraint | Detail |
|---|---|
| **No LLM generation** | Every response is verbatim excerpts from retrieved documents |
| **Single Postgres** | One instance per host, one database per project (`hexa_assistant`) |
| **pgvector, not Qdrant** | Vector search runs in the same SQL query as BM25 + RBAC |
| **RBAC in WHERE clause** | Department access enforced by Postgres filtering, not post-hoc checks |
| **Socket-activated backend** | FastAPI runs with `--workers 1`, idle-stops after 10 minutes |
| **Batch ingestion only** | OCR, embedding, and NLP run in `ingest_batch.py`, never in API process |
| **Memory caps** | Postgres ~200MB, Nginx ~30MB, Backend 400MB (nomic embedding model), ingestion ~600MB transient |
| **Audit logging** | Every query logged with user, retrieved docs, confidence, timestamp |

---

## Tech Stack

### Backend (FastAPI)
| Component | Technology | Purpose |
|---|---|---|
| Web framework | **FastAPI 0.141.1** | REST API with automatic OpenAPI docs |
| Server | **Uvicorn 0.52.1** | ASGI server, `--workers 1` (socket-activated) |
| Database | **PostgreSQL 16 + pgvector** | BM25 search + vector similarity in single query |
| Driver | **psycopg 3.3.4** | Connection pooling, cursor access |
| Embeddings | **FastEmbed 0.8.0** | `nomic-ai/nomic-embed-text-v1.5-Q` (768-dim, ~137MB) |
| Inference runtime | **ONNX Runtime 1.28.0** | Runs FastEmbed model |
| Auth | **PyJWT 2.13.0** | HS256-signed tokens with RBAC claims |
| Config | **Pydantic 2.13.4** | Type-safe settings with env-var binding |
| Text processing | **RapidFuzz 3.14.5** | Fuzzy matching for spell correction |
| Batch ingestion | **pdfplumber 0.11.6**, **python-docx 1.2.0** | Text extraction from PDF/DOCX |

### Frontend (Next.js)
| Component | Technology | Purpose |
|---|---|---|
| Framework | **Next.js 14** | Static export (no SSR) |
| Styling | **Tailwind CSS** | Utility-first styling |
| Language | **TypeScript** | Type safety |
| Auth | Custom JWT client | Browser-side token management |

### Infrastructure
| Layer | Technology | Purpose |
|---|---|---|
| Reverse proxy | **Nginx (alpine)** | TLS termination, static file serving |
| Container | **Docker Compose** | Postgres + Nginx shared service |
| Process manager | **systemd socket-activation** | Backend starts on-demand, idle-stops |
| CI/CD | **GitHub Actions** | Unit tests + evaluation benchmarks |

---

## How It Works

The request-serving path has **zero LLM calls**. Here's the complete flow from query to response:

### 1. Request Reception (`main.py`)
- Nginx receives the HTTP request
- Socket-activated FastAPI starts on-demand (avoids idle resource usage)
- JWT extracted from Authorization header, verified via `auth/jwt_handler.py`
- RBAC claims (role, department, allowed_departments) extracted from token

### 2. Query Processing (`query_processing/pipeline.py`)
Pure, deterministic transformation — no network calls or model loading:

```
Raw query: "What are the credit score requirements for VA loans?"
    ↓ normalize (lowercase, unicode normalize)
    ↓ spell_correct (RapidFuzz-based phrase repair)
    ↓ split_into_sub_queries (multi-question detection via delimiter recognition)
    ↓ entity_extraction (domain-specific entity matching)
    ↓ intent_detection (general, eligibility, documents, rates, ...)
    → QueryPlan(sub_queries=[SQ(...), SQ(...)])
```

### 3. Hybrid Search (`search/hybrid_orchestrator.py`)
A **single SQL query** combines everything (illustrative shape):

```sql
SELECT chunks.*, 
       ts_rank_cd(chunks.fts, plainto_tsquery($1)) AS bm25_score,
       GREATEST(1 - (chunks.embedding <=> :v1), ...variants) AS vec_score,
       ent.hits AS entity_hits        -- GraphRAG-lite channel
FROM document_chunks chunks
LEFT JOIN (SELECT chunk_id, COUNT(DISTINCT entity) AS hits
           FROM chunk_entity_links WHERE entity = ANY(:entities)
           GROUP BY chunk_id) ent ON ent.chunk_id = chunks.id
WHERE chunks.is_active = true
  AND chunks.is_approved = true          -- version filter
  AND chunks.department = ANY($3)       -- RBAC filter (in WHERE, not post-hoc)
ORDER BY rrf_score DESC                 -- RRF over BM25 + vector + entity ranks
LIMIT 25;
```

BM25 scores text relevance using PostgreSQL's full-text search (`tsvector`); vector search uses pgvector's `vector_cosine_ops` HNSW index, with **best similarity across all deterministic Multi-Query variants** (`query_expansion.generate_query_variants`). The `chunk_entity_links` join adds a third RRF channel keyed on canonical query entities. All channels share the same WHERE clause for RBAC — **no post-hoc filtering**.

### 4. Ranking (`ranking/rrf.py`)
Reciprocal Rank Fusion combines BM25-ranked and vector-ranked lists:

```python
def rank_fusion(bm25_ranked, vector_ranked, chunk_lookup, k=60):
    """RRF: each chunk gets score = Σ(1 / (k + rank)) across lists."""
    # No learned weights — pure position-based fusion
    # Configurable k parameter in ranking/weights_config.py
```

### 5. Response Packaging (`response/package_builder.py`)
Assembles the response package — **verbatim excerpts only**:

```
ResponsePackage {
    response_id: UUID (audit correlation),
    title: "Derived from top excerpt's document title",
    excerpts: [
        { text: "The minimum credit score for...",  ← verbatim chunk
          source: {title, section, chunk_type},
          confidence: 87.5,
          related_sub_queries: [...] }
    ],
    confidence: 87.5,  ← weighted average of top excerpt confidences
    routing: "answer"  ← determined by confidence_thresholds.py
    related_questions: [...]  ← from multi_question.py
}
```

**Confidence routing** (`response/confidence_thresholds.py`):
- **90+** → `"answer"` (high confidence)
- **75-89** → `"partial"` (some relevant results)
- **50-74** → `"partial"` (low confidence, needs human review)
- **<50** → `"no_answer"` (redirect to human)

### 6. Validation (`response/validation.py`)
Safety-net validation (not the only RBAC enforcement — that's in the SQL WHERE clause):
- Re-checks document department access
- Re-checks document approval status and version flags
- Does **not** check confidence thresholds — that is handled by `confidence_thresholds.py`
  (`route_by_confidence`), which sets `package.routing`. Low-confidence results return a
  graceful `"no_answer"` response, not a server error.

### 7. Audit Logging (`audit/audit_logger.py`)
Every query is logged to `audit_log` table:
```
user_id, query, sub_queries (JSON), retrieved_ids (array),
confidence, response_id, outcome, latency_ms, created_at
```

---

## Project Structure

```
HEXTA/
├── backend/                    # FastAPI application
│   ├── app/
│   │   ├── api/v1/           # API endpoints (auth, search, documents, feedback, analytics)
│   │   ├── audit/            # Structured audit logging
│   │   ├── auth/             # JWT, RBAC, permissions
│   │   ├── db/postgres/      # Schema, session pooling, models
│   │   ├── documents/        # Ingestion pipeline (batch-only)
│   │   │   └── chunking/      # Structural chunker
│   │   ├── knowledge_gap/    # Low-confidence query detection
│   │   ├── query_processing/  # Query normalization, spell correction, expansion
│   │   ├── ranking/           # RRF fusion, configurable weights
│   │   ├── response/          # Package builder, confidence thresholds, validation
│   │   ├── search/            # Hybrid BM25 + pgvector orchestrator
│   │   ├── config.py          # Pydantic-settings configuration
│   │   ├── dependencies.py    # FastAPI dependency injection
│   │   └── main.py           # FastAPI app with lifespan
│   ├── tests/
│   │   ├── unit/             # 20+ unit tests
│   │   ├── integration/      # RBAC enforcement tests
│   │   └── conftest.py       # DB mocking for unit tests
│   ├── requirements.txt      # Pinned dependencies
│   ├── Dockerfile            # python:3.11-slim, --workers 1
│   └── debug_imports.py      # Import verification
│
├── frontend/                  # Next.js 14 static frontend
│   ├── app/                  # Pages (static export)
│   ├── components/           # Search, feedback components
│   ├── lib/                  # API client, JWT auth
│   └── styles/               # Tailwind CSS
│
├── evaluation/               # Benchmark framework
│   ├── datasets/             # eval_20_questions.jsonl
│   ├── metrics/              # hit_rate, precision, recall, MRR, nDCG
│   ├── reports/              # Benchmark output
│   └── run_benchmark.py      # Evaluation runner
│
├── shared-host-infra-scaffold/  # Production deployment
│   ├── infra/
│   │   ├── shared/           # docker-compose (Postgres + Nginx)
│   │   ├── systemd/         # Socket-activated backend service
│   │   └── scripts/         # migrate_db.sh, run_ingestion.sh
│   └── postgres/init/       # Schema initialization
│
├── .github/workflows/       # CI/CD (ci.yml, deploy.yml, eval_on_pr.yml)
├── CLAUDE.md               # Architectural rules
└── README.md               # This file
```

---

## Quick Start (Development)

### Required toolchain
- Python 3.11.x for the backend
- Node.js 20.x for the frontend
- npm 10.x or newer

```bash
# 1. Start PostgreSQL with pgvector
docker run -d --name postgres \
  -e POSTGRES_USER=admin -e POSTGRES_PASSWORD=adminpass \
  -e POSTGRES_DB=hexa_assistant \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# 2. Create and activate a Python virtual environment
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows PowerShell
# or: source .venv/bin/activate  # macOS/Linux

# 3. Install backend dependencies
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

# 4. Set environment variables
# Copy the example env file if present and adjust values as needed
# . .env

# 5. Run the API
.venv\Scripts\python.exe -m uvicorn app.main:app --workers 1 --reload

# 6. Run tests
.venv\Scripts\python.exe -m pytest tests/unit/ -q

# 7. Run frontend (separate terminal)
cd ../frontend
npm ci
npm run dev

# 8. Run evaluation benchmark
cd ../backend
.venv\Scripts\python.exe -m evaluation.run_benchmark --output-dir evaluation/reports
```

---

## Production Deployment

```bash
# 1. Shared Postgres + Nginx
cd shared-host-infra-scaffold/infra/shared
cp .env.example .env
docker compose up -d

# 2. Install socket-activated backend
sudo cp infra/systemd/hexa-backend.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hexa-backend.socket
sudo systemctl enable --now hexa-backend-idle.timer

# 3. Set secrets
export HEXA_DATABASE_URL=postgresql://hexa_app:S3CRET@127.0.0.1:5432/hexa_assistant
export HEXA_JWT_SECRET="at-least-32-char-secret-key-here"

# 4. Seed schema (if not auto-created)
bash infra/scripts/migrate_db.sh

# 5. Run batch ingestion
bash infra/scripts/run_ingestion.sh

# 6. Build frontend (static)
cd frontend
npm run build && npx serve -s out -p 3000
```

---

## Testing

Tests are split into **unit** (no database) and **integration** (RBAC enforcement):

```bash
cd backend
.venv\Scripts\python.exe -m pytest tests/unit/ -q
.venv\Scripts\python.exe -m pytest tests/ -q
```

**Unit test modules:**
- `test_backend_skeleton.py` — App startup, auth, JWT, RBAC, endpoints (29 tests)
- `test_documents.py` — Ingestion validation, chunking, metadata (8 tests)
- `test_search_ranking.py` — BM25 query building, metadata filters, RRF (12 tests)
- `test_response.py` — Confidence thresholds, package builder, validation (16 tests)
- `test_spell_correcton.py` — Spell correction phrase repair (4 tests)

**Integration tests:**
- `test_rbac_prefilter.py` — RBAC enforcement in SQL WHERE clause (5 tests)

---

## Evaluation & Benchmarks

The evaluation framework runs 20 test questions against the query-processing pipeline and measures accuracy + latency:

```bash
cd backend
.venv/bin/python -m evaluation.run_benchmark --output-dir evaluation/reports
```

**Latest results** (`evaluation/reports/benchmark_20260802_171344.json`):
- Sub-question decomposition accuracy: 100%
- Query processing latency: ~1.6ms average
- Total queries: 20
- All test cases passed

Results are uploaded as artifacts in CI and used for regression detection on PRs.
