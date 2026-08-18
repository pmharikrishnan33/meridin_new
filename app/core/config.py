from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WEBHOOK_MAX_BODY_BYTES = 256 * 1024  # 256 KB — Meta payloads rarely exceed 100 KB
RATE_LIMIT_DEFAULT_WINDOW = 60
RATE_LIMIT_DEFAULT_MAX_REQUESTS = 30


class Settings(BaseSettings):
    """
    Global application configuration.

    NOTE:
    This file should only contain application-level settings.
    Tenant/client-specific settings belong in MongoDB (clients collection).
    """

    # ==========================================================
    # APPLICATION
    # ==========================================================

    APP_NAME: str = "Meridin"
    APP_VERSION: str = "1.0.0"

    DEBUG: bool = False
    WHATSAPP_GRAPH_API_VERSION: str = "v18.0"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        """Accept common deployment environment names for DEBUG."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod"}:
                return False
            if normalized in {"development", "dev", "debug"}:
                return True
        return value

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Shared application secret used as the global fallback for internal
    # signing / HMAC verification when a tenant-specific or explicit
    # webhook secret is not supplied.
    APP_SECRET: str

    # ==========================================================
    # DATABASE
    # ==========================================================

    MONGODB_URI: str

    DATABASE_NAME: str = "meridin"

    # Set this to true in deployments where MongoDB must be available at startup.
    # Keeping it false allows the ML chat API to run locally without a database.
    MONGODB_REQUIRED: bool = False

    # ==========================================================
    # ML MODELS
    # ==========================================================

    INTENT_MODEL: str = "models/intent_model.pkl"

    INTENT_VECTORIZER: str = "models/intent_vectorizer.pkl"

    ENTITY_MODEL: str = "models/entity_model.pkl"

    ENTITY_VECTORIZER: str = "models/entity_vectorizer.pkl"

    # ==========================================================
    # DATA FILES
    # ==========================================================

    NORMALIZATION_FILE: str = "data/normalization.json"

    VOCABULARY_FILE: str = "data/vocabulary.json"

    # ==========================================================
    # CACHE
    # ==========================================================

    REDIS_URL: str = "redis://localhost:6379/0"

    # ==========================================================
    # LOGGING
    # ==========================================================

    LOG_LEVEL: str = "INFO"

    # ==========================================================
    # AI / OPENROUTER
    # ==========================================================

    OPENROUTER_API_KEY: str

    OPENROUTER_MODEL: str = "meta-llama/llama-3.1-8b-instruct"

    # ==========================================================
    # WHATSAPP / META
    # ==========================================================

    WHATSAPP_VERIFY_TOKEN: str = ""

    WHATSAPP_PHONE_NUMBER_ID: str = ""

    WHATSAPP_ACCESS_TOKEN: str = ""

    # Optional shared secret used to verify the X-Hub-Signature-256 header on
    # POST requests to the webhook. When per-tenant secrets are stored in
    # MongoDB they take precedence over this setting, and ``APP_SECRET`` is
    # used as the final fallback for a single-secret deployment.
    WHATSAPP_WEBHOOK_SECRET: str = ""

    # ==========================================================
    # RATE LIMITING
    # ==========================================================

    RATE_LIMIT_ENABLED: bool = True

    @field_validator("RATE_LIMIT_ENABLED", mode="before")
    @classmethod
    def _parse_rate_limit_enabled(cls, value: str | bool) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    RATE_LIMIT_WINDOW_SECONDS: int = RATE_LIMIT_DEFAULT_WINDOW

    RATE_LIMIT_MAX_REQUESTS: int = RATE_LIMIT_DEFAULT_MAX_REQUESTS

    # ==========================================================
    # PYDANTIC SETTINGS
    # ==========================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Loads settings once and caches them.
    """
    return Settings()


settings = get_settings()
