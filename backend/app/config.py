"""Application configuration.

Reads settings from environment variables with the HEXA_ prefix
(e.g. HEXA_DATABASE_URL), plus an optional .env file. All values are
plain configuration with documented defaults; ranking weights and
confidence thresholds deliberately live in their own modules
(ranking/weights_config.py, response/confidence_thresholds.py) so any
change to them has to pass the evaluation benchmark gate first
(CLAUDE.md rule 7).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HEXA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Core ---
    app_name: str = "Hexta"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # --- Database ---
    # postgresql://user:password@host:port/dbname
    database_url: str = "postgresql://hexa_app:devpass@127.0.0.1:5432/hexa_assistant"
    database_pool_max: int = 4
    database_pool_timeout_s: int = 30

    # --- Auth ---
    # No default on purpose: an empty secret would let anyone mint a valid
    # admin JWT. The validator below hard-fails on startup instead of
    # silently running with a forgeable key.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 480

    # --- CORS ---
    # Comma-separated list of allowed origins; "*" in non-production only.
    cors_origins: str = "*"

    # --- Embeddings (query-time, always-on process) ---
    embedding_enabled: bool = True
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5-Q"
    embedding_cache_dir: str = "nlp_models/embeddings"

    # --- LLM synthesis tier (docs/LLM_INTEGRATION_PLAN.md Stage 1) ---
    # OFF by default: the extractive pipeline is the product. When enabled,
    # top evidence is sent to Claude to synthesize a cited answer, which
    # must pass the grounding validator (response/grounding.py) or the
    # extractive answer_phrase is used instead. The key is injected via
    # env (HEXA_ANTHROPIC_API_KEY maps here) — never committed.
    llm_enabled: bool = False
    llm_api_key: str = ""
    # Two-tier routing (Stage 2): simple questions go to the fast/cheap
    # model, complex ones (comparisons, multi-part, long explanatory
    # questions — see llm_synthesis.is_complex_question) to the stronger
    # one. Both must support the Messages API.
    llm_simple_model: str = "claude-haiku-4-5"
    llm_complex_model: str = "claude-sonnet-4-5"
    llm_timeout_ms: int = 4000
    llm_max_tokens: int = 600

    # --- Response cache (Stage 0, Postgres-native — no Redis) ---
    response_cache_enabled: bool = True

    # --- Storage ---
    storage_pending_dir: str = "storage/pending"
    storage_processed_dir: str = "storage/processed"
    max_upload_bytes: int = 20 * 1024 * 1024

    # --- Search ---
    bm25_limit: int = 25
    max_sub_queries: int = 6
    max_alias_ngram: int = 3

    # --- Response ---
    max_excerpt_chars: int = 600
    max_evidence_docs: int = 3

    # --- Behavioural ---
    auto_create_schema: bool = True
    audit_enabled: bool = True

    # --- Cross-encoder reranker ---
    # Reorders the top rerank_top_k RRF candidates by scoring each
    # (query, chunk) pair together -- the signal neither BM25 nor the
    # bi-encoder can produce, since both score query and chunk apart.
    # Enabled by default now that it runs on the FastEmbed/onnxruntime
    # stack already in the image (~80MB quantized) instead of
    # transformers/torch, which never fit the memory cap. Set
    # HEXA_RERANK_ENABLED=false to fall back to plain RRF order.
    # Any change here must be checked against the <200ms p95 budget
    # (CLAUDE.md rule 6) via evaluation/run_benchmark.py.
    #
    # rerank_top_k is set by that budget, not by taste: cross-encoder
    # cost is linear in candidates, and on the eval set p95 measured
    # 179.8ms at 5, 208.7ms at 6 and 244.5ms at 10. Rank quality is flat
    # from 5 upward (hit_rate@3 92.3% and mrr@3 62.8% at all three), so 5
    # buys the whole improvement and is the only one inside budget.
    rerank_enabled: bool = True
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_cache_dir: str = "nlp_models/reranker"
    rerank_top_k: int = 5

    @model_validator(mode="after")
    def _check_jwt_secret(self) -> "Settings":
        if not self.jwt_secret:
            # An empty HS256 key lets anyone forge a valid admin token in
            # ANY environment, including development and any misconfigured
            # deploy that forgets to set HEXA_JWT_SECRET. Fail fast instead.
            raise ValueError(
                "HEXA_JWT_SECRET must be set (generate one with "
                "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` "
                "and export it before starting the backend)."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
