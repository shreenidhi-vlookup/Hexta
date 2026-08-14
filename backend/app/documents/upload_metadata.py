"""Category sidecar written at upload, read at ingest.

The upload endpoint is forbidden from ingesting (CLAUDE.md rule 5), and
the batch ingester runs as a separate process that sees only the files in
``storage/pending/``. A small JSON file named ``<stored name>.meta.json``
carries the admin's category choice across that boundary.

Named after the document rather than keyed in a shared index so the pair
moves, and is cleaned up, as one unit -- and so a partially-written batch
can never associate a category with the wrong file.

The extension is deliberately ``.json``: ``ingest_batch.main()`` selects
files by document suffix, so sidecars are never mistaken for uploads.

Reads never raise. A corrupt sidecar degrades to "no choice recorded",
which falls back to content detection; letting it raise would strand the
document in pending/ on every subsequent batch run.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SIDECAR_SUFFIX = ".meta.json"

# Only these keys are honoured; anything else in the file is ignored.
_ALLOWED_KEYS = ("doc_type", "department")


def sidecar_path(document_path: Path) -> Path:
    """Path of the sidecar belonging to ``document_path``."""
    return document_path.with_name(document_path.name + SIDECAR_SUFFIX)


def write_sidecar(
    document_path: Path,
    doc_type: str | None,
    department: str | None,
) -> Path | None:
    """Record the admin's category choice. Returns None if there was none."""
    payload = {
        key: value
        for key, value in (("doc_type", doc_type), ("department", department))
        if value
    }
    if not payload:
        return None
    path = sidecar_path(document_path)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def read_sidecar(document_path: Path) -> dict[str, str]:
    """Read the recorded choice, or ``{}`` when there is none to be had."""
    path = sidecar_path(document_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable sidecar %s: %s", path.name, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("Ignoring non-object sidecar %s", path.name)
        return {}
    return {
        key: data[key]
        for key in _ALLOWED_KEYS
        if isinstance(data.get(key), str) and data[key]
    }


def move_sidecar(document_path: Path, dest_dir: Path) -> None:
    """Move a document's sidecar into ``dest_dir``; no-op when absent.

    The sidecar travels with the document into processed/ rather than
    being deleted, so re-ingesting a processed file keeps its category.
    """
    path = sidecar_path(document_path)
    if not path.exists():
        return
    try:
        path.rename(dest_dir / path.name)
    except OSError as exc:
        logger.warning("Could not move sidecar %s: %s", path.name, exc)
