"""Shared fixtures and mocks for unit tests.

These tests must run without a live Postgres instance. We mock the
``acquire`` context manager in the session module so endpoints that
call ``acquire()`` get a fake connection returning no rows.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _fake_conn() -> MagicMock:
    """Return a connection whose cursor.fetchall returns no rows."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


# Patch acquire at import time so tests don't need to repeat the decorator.
patch("app.db.postgres.session.acquire", return_value=_fake_conn()).start()
