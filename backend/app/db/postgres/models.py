"""Row helpers for the persistence layer.

Keeps small, dependency-free row→dict mapping here so the query/search
modules can stay focused on logic. No ORM — a knowledge assistant with
one small Postgres schema does not justify SQLAlchemy's footprint on a
shared 1 GiB host.
"""

from __future__ import annotations

import hashlib


def content_hash(content: str) -> str:
    """Deterministic hash used for chunk-level deduplication."""
    return hashlib.sha256(content.strip().lower().encode("utf-8")).hexdigest()
