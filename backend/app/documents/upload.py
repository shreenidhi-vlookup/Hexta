"""Document upload API endpoint.

Per CLAUDE.md rule 5: validates and writes to storage/pending/ only.
Does NOT call ingestion logic. Ingestion runs separately via
infra/scripts/run_ingestion.sh → app.documents.ingest_batch
"""
