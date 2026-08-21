#!/usr/bin/env bash
#
# Runs the document ingestion pipeline (OCR, chunking, entity
# extraction, embedding generation, indexing) as a one-shot batch job.
#
# This deliberately does NOT run inside the FastAPI process. The
# embedding model is the heaviest component in the stack —
# loading it into the always-on API process means paying that RAM
# cost 24/7 even when nobody is uploading documents. Running it
# here means the memory is only held for the duration of the job.
#
# Memory note (nomic-embed-text-v1.5-Q): loading + running the model
# peaks at ~275MB RSS, and scanned-PDF OCR (page rasterisation) can
# retain a comparable amount until process exit. Budget ~600MB of FREE
# memory for the duration of a batch — do not run concurrently with
# other heavy jobs on the shared host. If wrapping in a systemd scope,
# use `-p MemoryMax=700M` rather than the API service's 400M.
#
# Trigger this manually, via cron, or via a lightweight upload-queue
# consumer — never call it from inside app.main directly.

set -euo pipefail

cd /opt/projects/hexa/backend
source .venv/bin/activate

echo "[$(date -Iseconds)] Starting ingestion batch"
python -m app.documents.ingest_batch --queue-dir /opt/projects/hexa/storage/pending
echo "[$(date -Iseconds)] Ingestion batch complete"

# Process exits here — the embedding model RAM is
# released back to the OS, not held resident.
