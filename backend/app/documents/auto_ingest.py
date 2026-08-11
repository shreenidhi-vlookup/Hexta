"""Trigger document ingestion as a detached subprocess.

After an admin upload writes a file to ``storage/pending/``, the upload
endpoint calls :func:`trigger_ingestion` to spawn the batch ingestion
pipeline in a separate process. This keeps the embedding model (and the
rest of the ingestion pipeline) OUT of the serving process, satisfying
CLAUDE.md rule 5 ("document ingestion runs only in the batch script,
never inside a request handler") while still making uploaded documents
searchable automatically.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def _backend_root() -> Path:
    """Absolute path to the backend package root (parent of ``app/``)."""
    return Path(__file__).resolve().parents[2]


def _log_path() -> Path:
    """Path to the append-only ingestion log under storage/logs/."""
    pending = Path(settings.storage_pending_dir)
    return pending.parent / "logs" / "ingest.log"


def trigger_ingestion(pending_dir: str | Path | None = None) -> bool:
    """Spawn the ingestion batch pipeline as a detached subprocess.

    Args:
        pending_dir: Directory to scan for pending documents. Defaults to
            ``settings.storage_pending_dir``.

    Returns:
        True if the subprocess was spawned, False on failure.
    """
    queue_dir = str(pending_dir or settings.storage_pending_dir)
    backend_root = _backend_root()

    cmd = [
        sys.executable,
        "-m",
        "app.documents.ingest_batch",
        "--queue-dir",
        queue_dir,
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(backend_root) + os.pathsep + env.get("PYTHONPATH", "")
    )

    log_path = _log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_handle = open(log_path, "a", encoding="utf-8")
    except OSError:
        log_handle = subprocess.DEVNULL

    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )

    try:
        subprocess.Popen(
            cmd,
            cwd=str(backend_root),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=(sys.platform != "win32"),
            creationflags=creationflags,
        )
        logger.info("Spawned ingestion subprocess for %s", queue_dir)
        return True
    except Exception as exc:
        logger.error("Failed to spawn ingestion subprocess: %s", exc)
        if log_handle is not subprocess.DEVNULL:
            log_handle.close()
        return False
