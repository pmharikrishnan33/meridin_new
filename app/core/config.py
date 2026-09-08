from functools import lru_cache

from pydantic import field_validator, model_validator
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
    APP_ENV: str = "development"
    WHATSAPP_GRAPH_API_VERSION: str = "v23.0"

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

    # Application signing secret for dashboard access tokens.
    APP_SECRET: str
    TRUST_PROXY_HEADERS: bool = False
    CORS_ORIGINS: str = "http://localhost:5500,http://127.0.0.1:5500,http://localhost:5501,http://127.0.0.1:5501"

    # ==========================================================
    # ADMIN DASHBOARD
    # ==========================================================
    MERIDIN_ADMIN_EMAIL: str = ""
    MERIDIN_ADMIN_PASSWORD_HASH: str = ""

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

    REDIS_URL: str

    # ==========================================================
    # LOGGING
    # ==========================================================

    LOG_LEVEL: str = "INFO"
    LOG_TO_FILE: bool = False

    # ==========================================================
    # AI / OPENROUTER
    # ==========================================================

    OPENROUTER_API_KEY: str

    OPENROUTER_MODEL: str = "meta-llama/llama-3.1-8b-instruct"

    # ==========================================================
    # CLOUDFLARE R2 MEDIA STORAGE / GLOBAL SAFETY LIMITS
    # ==========================================================

    CLOUDFLARE_R2_ACCOUNT_ID: str = ""
    CLOUDFLARE_R2_ACCESS_KEY_ID: str = ""
    CLOUDFLARE_R2_SECRET_ACCESS_KEY: str = ""
    CLOUDFLARE_R2_BUCKET_NAME: str = ""
    CLOUDFLARE_R2_PUBLIC_URL: str = ""
    CLOUDFLARE_API_TOKEN: str = ""


    # ==========================================================
    # WHATSAPP / META
    # ==========================================================

    WHATSAPP_VERIFY_TOKEN: str = ""

    WHATSAPP_PHONE_NUMBER_ID: str = ""

    WHATSAPP_ACCESS_TOKEN: str = ""

    # Meta App Secret used to verify X-Hub-Signature-256.
    # Tenant-specific webhook secrets stored in MongoDB take precedence.
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

    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 900
    LOGIN_RATE_LIMIT_MAX_REQUESTS: int = 5

    OPENROUTER_TIMEOUT_SECONDS: float = 15.0
    OPENROUTER_MAX_TOKENS: int = 300
    OPENROUTER_MAX_MESSAGE_CHARS: int = 12000

    R2_UPLOAD_URL_TTL_SECONDS: int = 900
    R2_MAX_UPLOAD_BYTES: int = 5_000_000

    @model_validator(mode="after")
    def validate_production_settings(self):
        env = self.APP_ENV.strip().lower()
        if env in {"production", "prod"}:
            if self.DEBUG:
                raise ValueError("DEBUG must be false in production.")
            if len(self.APP_SECRET.strip()) < 32:
                raise ValueError("APP_SECRET must be at least 32 characters in production.")
            if self.APP_SECRET.strip() in {"replace-with-a-random-secret", "change-me", "secret"}:
                raise ValueError("A real APP_SECRET is required in production.")
            if self.MONGODB_REQUIRED is not True:
                raise ValueError("MONGODB_REQUIRED must be true in production.")
            if not self.CORS_ORIGINS.strip():
                raise ValueError("CORS_ORIGINS must be configured in production.")
        return self

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
