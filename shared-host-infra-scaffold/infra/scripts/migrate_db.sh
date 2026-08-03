#!/usr/bin/env bash
set -euo pipefail

# Seed the database with initial schema + users.
# Run this against the shared Postgres instance.

cd "$(dirname "$0")/../.."

source .venv/bin/activate 2>/dev/null || true

echo "Creating schema..."
python -m app.db.postgres.schema

echo "Seeding users..."
python -m app.db.postgres.seed_db

echo "Done."