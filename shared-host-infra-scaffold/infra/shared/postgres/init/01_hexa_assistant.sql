-- Runs once, on first container start, via docker-entrypoint-initdb.d.
-- Add one file like this per project — each project gets its own
-- database inside the ONE shared Postgres instance, not its own
-- Postgres process.
--
-- The application role password is read from the environment so it is
-- never committed to the repo. It is supplied via docker-compose env
-- (POSTGRES_APP_PASSWORD) at container initialization time — see
-- infra/shared/docker-compose.yml, which requires it in its .env. The
-- backend then connects as this role using the same value (backend/.env
-- HEXA_DATABASE_URL).

CREATE DATABASE hexa_assistant;

\connect hexa_assistant

CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector, replaces Qdrant

-- Role password comes from the container's POSTGRES_APP_PASSWORD env var
-- (never a committed literal). \getenv is psql's env-var reader (pg15+).
\getenv app_password POSTGRES_APP_PASSWORD
CREATE ROLE hexa_app LOGIN PASSWORD :'app_password';
GRANT ALL PRIVILEGES ON DATABASE hexa_assistant TO hexa_app;
GRANT ALL PRIVILEGES ON SCHEMA public TO hexa_app;
