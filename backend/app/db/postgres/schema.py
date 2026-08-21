"""Idempotent schema initialization.

Runs `CREATE TABLE IF NOT EXISTS` statements. Safe to run on every
startup (dev default) or via `scripts/migrate_db.sh` in production.

NOTE: this is a deliberate simplification of the originally-documented
Alembic migration approach: for a knowledge assistant with one small
Postgres schema, an idempotent DDL script is lighter than a full
migration framework and keeps the shared host's dependency footprint
small. If the schema ever grows to need multi-step data migrations,
introduce Alembic then — not before.
"""

from __future__ import annotations

import psycopg

from app.db.postgres.session import acquire

DDL_STATEMENTS: list[str] = [
    # --- Users ---
    """
    CREATE TABLE IF NOT EXISTS users (
        id                  BIGSERIAL PRIMARY KEY,
        email               TEXT NOT NULL UNIQUE,
        password_hash       TEXT NOT NULL,
        full_name           TEXT,
        role                TEXT NOT NULL DEFAULT 'processor',
        department          TEXT NOT NULL DEFAULT 'general',
        allowed_departments TEXT[] NOT NULL DEFAULT '{}',
        is_active           BOOLEAN NOT NULL DEFAULT true,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Documents ---
    """
    CREATE TABLE IF NOT EXISTS documents (
        id         BIGSERIAL PRIMARY KEY,
        title      TEXT NOT NULL,
        source_path TEXT,
        doc_type   TEXT NOT NULL DEFAULT 'policy',
        department TEXT NOT NULL DEFAULT 'general',
        is_active  BOOLEAN NOT NULL DEFAULT true,
        is_approved BOOLEAN NOT NULL DEFAULT false,
        version    INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Document chunks (the searchable unit) ---
    """
    CREATE TABLE IF NOT EXISTS document_chunks (
        id           BIGSERIAL PRIMARY KEY,
        document_id  BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        content      TEXT NOT NULL,
        content_hash TEXT NOT NULL UNIQUE,
        summary      TEXT,
        embedding    vector(768),
        section      TEXT,
        chunk_type   TEXT NOT NULL DEFAULT 'paragraph',
        department   TEXT NOT NULL DEFAULT 'general',
        is_active    BOOLEAN NOT NULL DEFAULT true,
        is_approved  BOOLEAN NOT NULL DEFAULT false,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        fts          tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
    )
    """,
    # --- Audit log (every query, immutable, compliance artifact) ---
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id            BIGSERIAL PRIMARY KEY,
        user_id       BIGINT,
        query         TEXT NOT NULL,
        sub_queries   JSONB,
        retrieved_ids BIGINT[],
        confidence    DOUBLE PRECISION,
        response_id   TEXT,
        outcome       TEXT,
        latency_ms    DOUBLE PRECISION,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Feedback ---
    """
    CREATE TABLE IF NOT EXISTS feedback (
        id          BIGSERIAL PRIMARY KEY,
        user_id     BIGINT,
        response_id TEXT NOT NULL,
        rating      SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
        comment     TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Knowledge gaps (low-confidence / no-answer signals) ---
    """
    CREATE TABLE IF NOT EXISTS knowledge_gaps (
        id         BIGSERIAL PRIMARY KEY,
        query      TEXT NOT NULL,
        intent     TEXT,
        confidence DOUBLE PRECISION,
        acknowledged BOOLEAN NOT NULL DEFAULT false,
        acknowledged_by BIGINT REFERENCES users(id),
        acknowledged_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- User settings (per-user UI preferences) ---
    """
    CREATE TABLE IF NOT EXISTS user_settings (
        id                  BIGSERIAL PRIMARY KEY,
        user_id             BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        show_related_questions BOOLEAN NOT NULL DEFAULT true,
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Doc-derived aliases / acronyms (harvested at ingestion) ---
    """
    CREATE TABLE IF NOT EXISTS term_aliases (
        id                  BIGSERIAL PRIMARY KEY,
        alias               TEXT NOT NULL UNIQUE,
        canonical           TEXT NOT NULL,
        document_id         BIGINT REFERENCES documents(id) ON DELETE CASCADE,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # --- Entity graph (GraphRAG-lite) ---
    # Chunk→entity edges harvested at ingestion (documents/entity_extraction.py).
    # This is the *compliant* GraphRAG substitute: a graph-shaped index that
    # lives inside the existing Postgres database — no graph store, no new
    # container (CLAUDE.md rules 2–3). Query time joins it as a third
    # retrieval channel in the same SQL statement as BM25+vector (rule 3).
    """
    CREATE TABLE IF NOT EXISTS chunk_entity_links (
        id          BIGSERIAL PRIMARY KEY,
        chunk_id    BIGINT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
        entity      TEXT NOT NULL,
        entity_type TEXT NOT NULL DEFAULT 'term'
    )
    """,
]

INDEX_STATEMENTS: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks (document_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_active ON document_chunks (department, is_active, is_approved)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_fts ON document_chunks USING gin (fts)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_content_hash ON document_chunks (content_hash)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_settings_user_id ON user_settings (user_id)",
    # Entity-graph lookup paths: query-time joins by entity, and
    # chunk-deletion cascades stay cheap during re-ingestion.
    "CREATE INDEX IF NOT EXISTS idx_entity_links_entity ON chunk_entity_links (entity)",
    "CREATE INDEX IF NOT EXISTS idx_entity_links_chunk ON chunk_entity_links (chunk_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_links_triple ON chunk_entity_links (chunk_id, entity, entity_type)",
]


# Phase 3a: Add client/audience columns (nullable, IF NOT EXISTS to preserve data).
# D5: idempotent ALTER TABLE ADD COLUMN IF NOT EXISTS in schema.py.
ALTER_STATEMENTS: list[str] = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS client_id TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS assigned_clients TEXT[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS assigned_cases TEXT[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS client_id TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS property_id TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS case_id TEXT",
    "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS client_id TEXT",
    "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS property_id TEXT",
    "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS case_id TEXT",
    "ALTER TABLE knowledge_gaps ADD COLUMN IF NOT EXISTS acknowledged BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE knowledge_gaps ADD COLUMN IF NOT EXISTS acknowledged_by BIGINT REFERENCES users(id)",
    "ALTER TABLE knowledge_gaps ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ",
    # Who put this document forward. Processors may upload but only admins
    # may approve, so the approver needs to see who is asking, and a
    # processor needs to see the status of their own uploads without being
    # handed the whole document list.
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS uploaded_by BIGINT REFERENCES users(id)",
    # Two-tier role model: the loan_officer / underwriter / compliance split
    # never diverged in behaviour, so it collapses into a single "processor"
    # tier (auth/rbac.py::STAFF_ROLE_HIERARCHY). Idempotent — re-running
    # matches nothing once migrated.
    #
    # This MUST ship in the same deploy as the hierarchy change: require_role
    # fails closed, so a new backend against un-migrated rows would 403 every
    # staff request.
    "UPDATE users SET role = 'processor' "
    "WHERE role IN ('loan_officer', 'underwriter', 'compliance')",
    # Keep the column default in step with the taxonomy so any future
    # INSERT that omits role creates a usable account instead of a
    # loan_officer that require_role will always reject.
    "ALTER TABLE users ALTER COLUMN role SET DEFAULT 'processor'",
    # Embedding model swap (bge-small-en-v1.5 384-dim → nomic-embed-text-v1.5
    # 768-dim). Old vectors are dimensionally incompatible and cannot be
    # cast, so they are nulled — a FULL RE-INGESTION is required after this
    # migration runs. Idempotent: matches nothing once the column is 768.
    """
    DO $emb$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_attribute a
            WHERE a.attrelid = 'document_chunks'::regclass
              AND a.attname = 'embedding'
              AND format_type(a.atttypid, a.atttypmod) = 'vector(384)'
        ) THEN
            ALTER TABLE document_chunks
                ALTER COLUMN embedding TYPE vector(768)
                USING NULL::vector(768);
        END IF;
    END
    $emb$;
    """,
]

# Index for client-scored retrieval (Phase 3a).
ALTER_INDEX_STATEMENTS: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_chunks_client ON document_chunks (client_id, department, is_active, is_approved)",
    "CREATE INDEX IF NOT EXISTS idx_documents_client ON documents (client_id, department, is_active, is_approved)",
]


def init_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        for ddl in DDL_STATEMENTS:
            cur.execute(ddl)
        for stmt in ALTER_STATEMENTS:
            cur.execute(stmt)
        for idx in INDEX_STATEMENTS:
            cur.execute(idx)
        for idx in ALTER_INDEX_STATEMENTS:
            cur.execute(idx)
    conn.commit()


def ensure_schema() -> None:
    """Idempotent; safe to call at app startup."""
    with acquire() as conn:
        init_schema(conn)
