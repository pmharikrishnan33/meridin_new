from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Global application configuration.

    NOTE:
    This file should only contain application-level settings.
    Tenant/client-specific settings belong in MongoDB (tenants collection).
    """

    # ==========================================================
    # APPLICATION
    # ==========================================================

    APP_NAME: str = "Meridin"
    APP_VERSION: str = "1.0.0"

    DEBUG: bool = True

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
