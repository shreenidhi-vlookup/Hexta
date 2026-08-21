"""Response cache — LLM_INTEGRATION_PLAN.md Stage 0.

Postgres-native exact-query cache (Redis stays banned per CLAUDE.md
rule 2). A cached entry is valid only while every contributing
document's version is unchanged, so re-ingestion or an approval flip
self-invalidates entries without a sweep job.

Cache keys are scoped: the RBAC scope fingerprint (role + departments +
client_id) is part of the key, so two users share an entry only when
they see exactly the same corpus. User identity is deliberately NOT in
the key — same scope ⇒ same answer.
"""

from __future__ import annotations

import hashlib
import json
import logging

from psycopg import Connection
from psycopg.types.json import Json

logger = logging.getLogger(__name__)


def compute_keys(query: str, history: list[dict], user: dict) -> tuple[str, str]:
    """Return ``(query_hash, scope_hash)`` for a request."""
    payload = json.dumps(
        {"q": query, "h": history}, sort_keys=True, default=str
    )
    query_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    departments = sorted(set((user.get("allowed_departments") or []) + [user.get("department", "")]))
    scope_payload = json.dumps({
        "role": user.get("role"),
        "dept": departments,
        "client": user.get("client_id"),
        "assigned_clients": sorted(user.get("assigned_clients") or []),
        "assigned_cases": sorted(user.get("assigned_cases") or []),
    }, sort_keys=True)
    scope_hash = hashlib.sha256(scope_payload.encode("utf-8")).hexdigest()
    return query_hash, scope_hash


def get_cached(conn: Connection, query_hash: str, scope_hash: str) -> dict | None:
    """Return the cached response dict, or None on miss/invalidation.

    Invalidation check: every document version recorded at store time must
    still match. A missing document also invalidates (it was deleted).
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT response, doc_versions FROM response_cache "
                "WHERE query_hash = %s AND scope_hash = %s",
                (query_hash, scope_hash),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.warning("response cache lookup failed: %s", exc)
        return None

    if row is None:
        return None

    stored_versions: dict = row["doc_versions"] or {}
    if stored_versions:
        ids = [int(doc_id) for doc_id in stored_versions]
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, version FROM documents WHERE id = ANY(%s)",
                (ids,),
            )
            current = {str(r["id"]): r["version"] for r in cur.fetchall()}
        if current != {str(k): v for k, v in stored_versions.items()}:
            return None

    return row["response"]


def store(
    conn: Connection,
    query_hash: str,
    scope_hash: str,
    query_text: str,
    response: dict,
    chunk_ids: list[int],
) -> None:
    """Best-effort cache write. Never raises — caching must not break
    the request path."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT d.id, d.version FROM documents d "
                "JOIN document_chunks c ON c.document_id = d.id "
                "WHERE c.id = ANY(%s)",
                (chunk_ids,),
            )
            versions = {str(r["id"]): r["version"] for r in cur.fetchall()}
            cur.execute(
                "INSERT INTO response_cache "
                "(query_hash, scope_hash, query_text, response, doc_versions) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (query_hash) DO UPDATE SET "
                "scope_hash = EXCLUDED.scope_hash, "
                "query_text = EXCLUDED.query_text, "
                "response = EXCLUDED.response, "
                "doc_versions = EXCLUDED.doc_versions, "
                "created_at = now()",
                (
                    query_hash,
                    scope_hash,
                    query_text,
                    Json(response),
                    Json(versions),
                ),
            )
        conn.commit()
    except Exception as exc:
        logger.warning("response cache store failed: %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass
