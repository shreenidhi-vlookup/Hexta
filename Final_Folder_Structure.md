# Mortgage CRM Intelligent Knowledge Assistant — Final Folder Structure (V3.2)

Reflects every decision made through the shared-host addendum: pgvector
replaces Qdrant, Redis/MinIO removed for MVP, ingestion runs as a batch
script, backend is socket-activated. This supersedes the earlier
single-project version.

```
hexa-knowledge-assistant/
│
├── frontend/                              # Next.js + TypeScript + Shadcn/UI
│   ├── src/
│   │   ├── app/
│   │   │   ├── (auth)/
│   │   │   │   ├── login/
│   │   │   │   └── layout.tsx
│   │   │   ├── (dashboard)/
│   │   │   │   ├── search/
│   │   │   │   ├── analytics/
│   │   │   │   ├── admin/
│   │   │   │   │   ├── documents/
│   │   │   │   │   └── users-roles/
│   │   │   │   └── layout.tsx
│   │   │   └── layout.tsx
│   │   │   # NOTE: no app/api/ route handlers — static export has no
│   │   │   # server runtime. Frontend calls FastAPI directly via
│   │   │   # lib/api-client.ts; JWT auth is enforced backend-side.
│   │   ├── components/
│   │   │   ├── ui/                        # Shadcn primitives
│   │   │   ├── search/
│   │   │   │   ├── SearchBar.tsx
│   │   │   │   ├── ResponsePackageCard.tsx
│   │   │   │   ├── ConfidenceBadge.tsx
│   │   │   │   ├── SourceCitation.tsx
│   │   │   │   └── RelatedQuestions.tsx
│   │   │   ├── feedback/
│   │   │   │   └── ThumbsFeedback.tsx
│   │   │   └── analytics/
│   │   │       └── KnowledgeGapTable.tsx
│   │   ├── hooks/
│   │   ├── lib/
│   │   │   ├── api-client.ts              # calls FastAPI directly, no BFF proxy
│   │   │   ├── auth.ts                    # JWT stored client-side, sent per-request
│   │   │   └── types.ts
│   │   └── styles/
│   ├── public/
│   ├── tests/
│   │   ├── unit/
│   │   └── e2e/
│   ├── .env.example
│   ├── next.config.js                     # output: 'export'
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   └── package.json
│
├── backend/                                # FastAPI application (socket-activated)
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py                       # imports weights_config.py / confidence_thresholds.py — file-based, benchmark-gated (not DB-driven)
│   │   ├── dependencies.py
│   │   │
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── auth.py
│   │   │   │   ├── search.py
│   │   │   │   ├── documents.py            # upload only — queues for batch ingestion
│   │   │   │   ├── feedback.py
│   │   │   │   ├── analytics.py
│   │   │   │   └── admin.py
│   │   │   └── router.py
│   │   │
│   │   ├── query_processing/
│   │   │   ├── spell_correction.py
│   │   │   ├── normalization.py
│   │   │   ├── intent_detection.py
│   │   │   ├── entity_extraction.py            # dictionary-based, no NER model
│   │   │   ├── query_expansion.py
│   │   │   └── classification.py
│   │   │
│   │   ├── search/                         # Hybrid Search Engine
│   │   │   ├── pgvector_search.py          # replaces vector_search.py (Qdrant removed)
│   │   │   ├── bm25_search.py              # PostgreSQL full text search
│   │   │   ├── metadata_filters.py         # RBAC + active-version pre-filter (enforced HERE)
│   │   │   └── hybrid_orchestrator.py      # single SQL query: BM25 + pgvector + filters
│   │   │
│   │   ├── ranking/
│   │   │   ├── rrf.py
│   │   │   ├── scoring.py
│   │   │   ├── weights_config.py           # initial default weights
│   │   │   └── reranker.py                 # ONNX Int8 cross-encoder, top-10 candidates
│   │   │
│   │   ├── response/
│   │   │   ├── package_builder.py
│   │   │   ├── confidence_thresholds.py    # initial default thresholds
│   │   │   └── validation.py               # redundant permission/version/confidence check
│   │   │
│   │   ├── documents/                       # shared by API (upload) and batch ingestion
│   │   │   ├── upload.py                    # API-side: validate + write to storage/pending/
│   │   │   ├── validation.py
│   │   │   ├── ingest_batch.py              # entry point for run_ingestion.sh — NOT imported by main.py (with OCR fallback)
│   │   │   ├── ocr.py                       # Tesseract OCR — optional fallback for scanned PDFs
│   │   │   ├── text_extraction.py           # pdfplumber for native PDFs; OCR for scans
│   │   │   ├── chunking/                    # wired into structural_chunker (tables + checklists)
│   │   │   │   ├── structural_chunker.py
│   │   │   │   ├── table_chunker.py
│   │   │   │   └── checklist_chunker.py
│   │   │   ├── metadata_extraction.py
│   │   │   ├── entity_extraction.py         # dictionary-based, batch-time
│   │   │   ├── embedding.py                 # FastEmbed + nomic-embed-text-v1.5-Q (768-dim), batch-time
│   │   │   └── indexing.py                  # writes to Postgres (rows + pgvector column)
│   │   │
│   │   ├── auth/
│   │   │   ├── jwt_handler.py
│   │   │   ├── rbac.py
│   │   │   └── permissions.py
│   │   │
│   │   ├── audit/
│   │   │   ├── audit_logger.py
│   │   │   └── models.py
│   │   │
│   │   ├── knowledge_gap/
│   │   │   └── gap_detector.py
│   │   │
│   │   └── db/
│   │       └── postgres/
│   │           ├── models.py                 # includes pgvector column type
│   │           ├── migrations/               # Alembic; enables `vector` extension
│   │           └── session.py                # connects to shared instance, own database
│   │
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── fixtures/
│   ├── alembic.ini
│   ├── requirements.txt                     # slim base image, no onnxruntime-on-alpine issues
│   ├── Dockerfile                           # python:3.11-slim, not alpine
│   └── .env.example
│
├── evaluation/
│   ├── datasets/
│   │   └── eval_100_questions.jsonl
│   ├── metrics/
│   │   ├── precision_recall.py
│   │   ├── mrr.py
│   │   ├── ndcg.py
│   │   ├── hit_rate.py
│   │   └── latency_benchmark.py             # includes reranker + cold-start latency checks
│   ├── run_benchmark.py
│   └── reports/
│
├── nlp_models/
│   ├── embeddings/
│   │   └── nomic-embed-text-v1.5-onnx-int8/
│   ├── reranker/
│   │   └── bge-reranker-base-onnx-int8/     # quantized, not raw PyTorch
│   └── gliner/
│       └── domain-entities-quantized/
│
├── storage/                                  # local filesystem — replaces MinIO
│   ├── pending/                              # uploaded, awaiting batch ingestion
│   └── processed/                            # ingested source files, kept for citation/audit
│
├── infra/
│   ├── README.md                             # setup steps, run in order
│   ├── systemd/
│   │   ├── hexa-backend.socket           # on-demand activation
│   │   ├── hexa-backend.service
│   │   ├── hexa-backend-idle.timer       # checks every 5 min
│   │   └── hexa-backend-idle.service
│   ├── scripts/
│   │   ├── idle_stop_watcher.sh              # stops backend after 10 min idle
│   │   └── run_ingestion.sh                  # batch NLP pipeline, exits when done
│   └── monitoring/
│       ├── prometheus/
│       │   └── prometheus.yml
│       └── grafana/
│           └── dashboards/
│               ├── search-latency.json
│               ├── confidence-distribution.json
│               ├── knowledge-gaps.json
│               └── cpu-credit-balance.json    # new — burstable CPU is now a tracked risk
│
├── scripts/
│   ├── seed_documents.py
│   └── migrate_db.sh
│
├── docs/
│   ├── Final_System_Design.md                # ← companion doc
│   ├── Final_Tech_Stack.md                   # ← companion doc
│   ├── chunking_strategy.md
│   ├── rbac_model.md
│   ├── confidence_and_thresholds.md
│   └── runbook.md
│
├── .github/
│   └── workflows/
│       ├── ci.yml
│       ├── eval_on_pr.yml
│       └── deploy.yml
│
├── .env.example
├── README.md
└── LICENSE

# Sibling directory, NOT inside this project's repo — shared across
# every project hosted on the same EC2 instance:
#
# /opt/shared-infra/
# ├── docker-compose.yml          # shared Postgres+pgvector, shared Nginx
# ├── postgres/
# │   ├── postgresql.conf
# │   └── init/
# │       ├── 01_hexa_assistant.sql
# │       └── 02_<other-project>.sql
# └── nginx/
#     └── conf.d/
#         ├── hexa-assistant.conf
#         └── <other-project>.conf
```

## What's different from the single-project version

| Removed | Why |
|---|---|
| `backend/app/db/qdrant/` | Replaced by pgvector column inside `db/postgres/` |
| `backend/app/cache/redis_client.py` | Redis dropped for MVP |
| MinIO service/config | Replaced by `storage/` on local filesystem |
| `frontend/src/app/api/` route handlers | Static export has no server runtime; frontend calls FastAPI directly |
| Per-project `docker-compose.yml` for Postgres | Now lives once in `/opt/shared-infra/`, not per project |

| Added | Why |
|---|---|
| `search/pgvector_search.py` + rewritten `hybrid_orchestrator.py` | BM25 + vector + metadata filter can now be one SQL query |
| `documents/ingest_batch.py` | Entry point for on-demand ingestion, decoupled from the API process |
| `infra/systemd/` | Socket activation + idle-timeout units for this project's backend |
| `storage/pending/` + `storage/processed/` | Local filesystem replacing MinIO |
| `cpu-credit-balance.json` dashboard | CPU contention across shared-host projects is now a tracked risk, not just RAM |

## Correction (post-review)

`config.py`'s annotation previously read "ranking weights / thresholds,
DB-driven," which contradicted `weights_config.py` /
`confidence_thresholds.py` being described elsewhere as benchmark-gated
defaults (CLAUDE.md rule #7, `Final_System_Design.md` §10.8). Corrected
to reflect the file-based design: `config.py` imports the values from
those two files rather than reading them from a database, so a change
can't bypass `eval_on_pr.yml`'s benchmark gate. If live DB-tunable config
is actually wanted, that's a deliberate architecture change requiring its
own enforcement mechanism (see review discussion) — not a doc fix.