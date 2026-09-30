"""Application settings, read from environment variables (.env in development).

Secrets (the database password, or a full DATABASE_URL) are SecretStr so they never show
up in reprs or logs.
"""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

SCHEMA_EMBED_DIM = 384  # the vector(384) columns in migration 0002


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # database
    postgres_user: str = "imagematch"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "imagematch"
    postgres_host: str = "localhost"
    postgres_port: int = 5433

    # ollama
    ollama_base_url: str = "http://localhost:11434"
    vision_model: str = "qwen3-vl:4b"
    embed_model: str = "all-minilm"
    embed_dim: int = SCHEMA_EMBED_DIM
    # the thinking model can reason for 5,000+ tokens at ~4-6 tokens/s on CPU
    ollama_timeout_s: float = 1800.0
    ollama_num_ctx: int = 8192
    vision_max_side: int = 512
    vision_max_retries: int = 2  # extra attempts after an invalid (schema-failing) response

    # images
    images_dir: str = "data/images"

    # low-confidence flag
    min_confidence: float = 0.60
    blur_threshold: float = 15.0  # measured on the corpus: blurred images 2-5, others 35+

    # mismatch guard
    similarity_threshold: float = 0.50  # tuned on eval/eval_set.json (see README)
    subject_sim_threshold: float = 0.80

    # background jobs
    job_max_attempts: int = 3
    job_backoff_base_s: float = 2.0
    job_poll_interval_s: float = 2.0
    # a running job whose heartbeat is older than this is assumed dead and requeued.
    # The heartbeat is refreshed before every model call, so this must exceed ollama_timeout_s.
    job_stale_after_s: float = 2400.0

    # cost tracking + budget guard. Local Ollama costs $0; the notional rates price each
    # call as if it went to a hosted API, so the budget guard has something to enforce.
    notional_usd_per_1m_input_tokens: float = 0.10
    notional_usd_per_1m_output_tokens: float = 0.40
    notional_usd_per_1m_embed_tokens: float = 0.02
    ai_budget_usd: float = 1.00
    ai_max_calls_per_job: int = 500

    default_tenant: str = "demo"
    log_level: str = "INFO"

    # tests point this at a separate database
    database_url_override: SecretStr | None = Field(default=None, alias="DATABASE_URL")

    @field_validator("embed_dim")
    @classmethod
    def embed_dim_matches_schema(cls, v: int) -> int:
        if v != SCHEMA_EMBED_DIM:
            raise ValueError(
                f"EMBED_DIM={v} but the database stores vector({SCHEMA_EMBED_DIM}); "
                "a different embedding size needs a new migration"
            )
        return v

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override.get_secret_value()
        # URL.create escapes the password, so characters like @ : / # ? are safe in it
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
