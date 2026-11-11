"""Environment-based application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AutoApprovableRisk = Literal["read", "create", "modify"]


def _is_set(value: SecretStr | None) -> bool:
    return value is not None and bool(value.get_secret_value())


class Settings(BaseSettings):
    """All runtime configuration. Values come from environment variables or `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Autonomous Atlassian AI Agent"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    db_auto_create: bool = True  # dev/test bootstrap; production uses `alembic upgrade head`

    # --- Security ---
    admin_api_key: SecretStr | None = None
    credential_encryption_key: SecretStr | None = None
    jwt_secret: SecretStr | None = None
    jwt_ttl_minutes: int = 480
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None

    # --- Atlassian HTTP ---
    atlassian_allowed_host_suffixes: list[str] = [".atlassian.net"]
    atlassian_timeout_seconds: float = 30.0
    atlassian_max_retries: int = 4
    atlassian_backoff_base_seconds: float = 1.0
    atlassian_backoff_max_seconds: float = 30.0

    # --- LLM ---
    llm_provider: Literal["gemini", "openai"] = "gemini"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3-flash-preview"
    # Used in order when the primary model's daily free quota is used up (separate quotas).
    gemini_fallback_models: list[str] = ["gemini-3.1-flash-lite"]
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = 120.0
    llm_temperature: float = 0.1
    # Pace LLM calls client-side (0 = unlimited). Free Gemini tiers allow ~5-10/minute.
    llm_requests_per_minute: int = 8

    # --- Speech ---
    stt_provider: Literal["gemini", "openai", "none"] = "gemini"
    openai_stt_model: str = "gpt-4o-mini-transcribe"
    tts_provider: Literal["openai", "none"] = "none"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    max_audio_bytes: int = 15 * 1024 * 1024

    # --- Execution ---
    auto_approve_risks: list[AutoApprovableRisk] = ["read"]
    max_plan_operations: int = 100
    verification_retry_delay_seconds: float = 1.5

    @model_validator(mode="after")
    def _require_secrets_in_production(self) -> "Settings":
        if self.environment == "production":
            missing = [
                name
                for name, value in (
                    ("ADMIN_API_KEY", self.admin_api_key),
                    ("CREDENTIAL_ENCRYPTION_KEY", self.credential_encryption_key),
                    ("JWT_SECRET", self.jwt_secret),
                )
                if not _is_set(value)
            ]
            if missing:
                raise ValueError(f"Missing required production settings: {', '.join(missing)}")
        return self

    @property
    def open_dev_mode(self) -> bool:
        """No admin key outside production: requests run as an anonymous admin (local dev only)."""
        return self.environment != "production" and not _is_set(self.admin_api_key)


@lru_cache
def load_settings() -> Settings:
    """Load settings once per process."""
    return Settings()
