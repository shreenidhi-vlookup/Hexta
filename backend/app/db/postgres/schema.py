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
        role                TEXT NOT NULL DEFAULT 'loan_officer',
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
        is_approved BOOLEAN NOT NULL DEFAULT true,
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
        embedding    vector(384),
        section      TEXT,
        chunk_type   TEXT NOT NULL DEFAULT 'paragraph',
        department   TEXT NOT NULL DEFAULT 'general',
        is_active    BOOLEAN NOT NULL DEFAULT true,
        is_approved  BOOLEAN NOT NULL DEFAULT true,
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
]

INDEX_STATEMENTS: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks (document_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_active ON document_chunks (department, is_active, is_approved)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_fts ON document_chunks USING gin (fts)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_content_hash ON document_chunks (content_hash)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_settings_user_id ON user_settings (user_id)",
]


def init_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        for ddl in DDL_STATEMENTS:
            cur.execute(ddl)
        for idx in INDEX_STATEMENTS:
            cur.execute(idx)
    conn.commit()


def ensure_schema() -> None:
    """Idempotent; safe to call at app startup."""
    with acquire() as conn:
        init_schema(conn)
