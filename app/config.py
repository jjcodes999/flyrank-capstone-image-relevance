"""Application settings, read from environment variables (.env in development).

Secrets (the database password) are SecretStr so they never show up in reprs or logs.
"""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    embed_dim: int = 384
    ollama_timeout_s: float = 900.0
    ollama_num_ctx: int = 8192
    vision_max_side: int = 512
    vision_max_retries: int = 2  # extra attempts after an invalid (schema-failing) response

    # images
    images_dir: str = "data/images"

    # low-confidence flag
    min_confidence: float = 0.60
    blur_threshold: float = 40.0

    # mismatch guard
    similarity_threshold: float = 0.45
    subject_sim_threshold: float = 0.80

    # background jobs
    job_max_attempts: int = 3
    job_backoff_base_s: float = 2.0
    job_poll_interval_s: float = 2.0
    # a running job whose heartbeat is older than this is assumed dead and requeued.
    # One item can take ~10 min on CPU (3 vision attempts), so keep this well above that.
    job_stale_after_s: float = 1200.0

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
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        pw = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
