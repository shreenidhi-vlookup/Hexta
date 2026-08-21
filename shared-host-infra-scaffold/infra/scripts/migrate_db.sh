#!/usr/bin/env bash
set -euo pipefail

# Seed the database with initial schema + users.
# Run this against the shared Postgres instance.

cd /opt/projects/hexa/backend
source .venv/bin/activate 2>/dev/null || true

echo "Creating schema..."
# `python -m app.db.postgres.schema` only imports the module — schema.py has
# no __main__ block, so it never actually created anything. Call the real
# entry point instead.
python -c "from app.db.postgres.schema import ensure_schema; ensure_schema()"

echo "Seeding users..."
python -m scripts.seed_db

echo "Done."