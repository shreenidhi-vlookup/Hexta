"""FastAPI application entry point.

Run with:
    uvicorn app.main:app --workers 1 --fd 3

Socket-activated by systemd (hexa-backend.socket on port 8001).
Idle-stops after 10 minutes of no activity (hexa-backend-idle.timer).
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings
from app.db.postgres.schema import ensure_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Idempotent schema creation on startup; pool cleanup on shutdown."""
    if settings.auto_create_schema:
        ensure_schema()
    yield
    from app.db.postgres.session import _pool

    if _pool is not None:
        _pool.close()


app = FastAPI(
    title=settings.app_name,
    docs_url=f"{settings.api_prefix}/docs",
    redoc_url=f"{settings.api_prefix}/redoc",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)

# CORS — restricted in production, permissive in dev.
#
# allow_credentials=True is invalid combined with a wildcard origin per the
# CORS spec (browsers reject Access-Control-Allow-Origin: * on credentialed
# requests) — Starlette's CORSMiddleware will happily send that invalid
# combination anyway if asked. The app authenticates via a Bearer header,
# never cookies, so no request needs credentialed CORS in the wildcard
# (development) case; only an explicit origin list turns it on.
if settings.cors_origins == "*":
    allow_origins = ["*"]
    allow_credentials = False
else:
    allow_origins = settings.cors_origins.split(",")
    allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint — no DB dependency."""
    return {"status": "healthy", "timestamp": time.time()}


@app.get(f"{settings.api_prefix}/health")
async def api_health() -> dict:
    """API-level health check with DB connectivity."""
    from app.db.postgres.session import ping

    db_ok = ping()
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "timestamp": time.time(),
    }


app.include_router(api_router, prefix=settings.api_prefix)
