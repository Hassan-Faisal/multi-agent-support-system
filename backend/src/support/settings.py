"""Typed application settings, loaded from environment variables / .env.

Everything tunable lives here so behaviour is explicit and reviewable. Secrets use
SecretStr so they never end up in logs or reprs.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from support.db.urls import to_asyncpg_url, to_libpq_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SUPPORT_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True

    # ------------------------------------------------------------ database
    # Any PostgreSQL URL form works, including a hosted provider's URL pasted as-is (see db/urls.py).
    database_url: str = "postgresql+asyncpg://support:support@localhost:5432/support"
    db_pool_size: int = 10

    # ------------------------------------------------------------ LLMs
    # Any provider:model string accepted by langchain's init_chat_model. OpenAI by default;
    # "anthropic:..." also works after `pip install -e ".[anthropic]"`.
    llm_model: str = "openai:gpt-6.1-sol"  # specialists: tool use and customer-facing replies
    triage_model: str = "openai:gpt-6-luna"  # routing only: small, fast, cheap
    # Unset by default: some current models reject a custom temperature.
    llm_temperature: float | None = None
    # OpenAI tool calling on current models goes through the Responses API.
    openai_use_responses_api: bool = True
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    # Message window sent to the model (older turns stay in the checkpoint).
    max_context_messages: int = 40

    # ------------------------------------------------------------ RAG
    embedding_provider: Literal["openai", "hashing"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536  # must match the pgvector column (see migration 0001)
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    kb_dir: str = "knowledge_base"
    chunk_max_chars: int = 1200
    chunk_overlap_chars: int = 200
    retrieval_top_k: int = 4
    retrieval_candidates: int = 20  # per retriever, before rank fusion
    retrieval_min_score: float = 0.0  # RRF score floor; 0 keeps everything fused

    # ------------------------------------------------------------ security
    jwt_secret: SecretStr = SecretStr("dev-only-change-me-dev-only-change-me")
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 60 * 8
    cors_origins: list[str] = ["http://localhost:5173"]
    rate_limit_per_minute: int = 20
    enable_demo_accounts: bool = True  # exposes demo logins on the login page

    # ------------------------------------------------------------ agent guardrails
    max_handoffs_per_turn: int = 3
    max_tool_steps_per_agent: int = 8
    injection_block_threshold: float = 0.8
    # Route-check every customer message (catches off-topic chat and topic changes) rather
    # than only the first message of a conversation. One small-model call per turn.
    triage_every_turn: bool = True
    turn_timeout_s: float = 120.0

    # ------------------------------------------------------------ business policy
    refund_auto_approve_limit: Decimal = Decimal("50.00")
    refund_window_days: int = 30
    return_window_days: int = 30

    @property
    def async_database_url(self) -> str:
        """URL for SQLAlchemy + asyncpg."""
        return to_asyncpg_url(self.database_url)

    @property
    def psycopg_url(self) -> str:
        """Plain libpq URL for the LangGraph Postgres checkpointer (psycopg)."""
        return to_libpq_url(self.database_url)

    # ------------------------------------------------------------ web
    # Directory with the built React app. When set, the API also serves the UI, so the
    # whole product runs as a single service (used by the root Dockerfile).
    static_dir: str | None = None


@lru_cache
def get_settings() -> Settings:
    # Also export .env into the process environment: provider SDKs (OpenAI) and
    # LangSmith read their keys from os.environ, not from this Settings object. Real
    # environment variables still win over the file.
    load_dotenv(".env", override=False)
    return Settings()
