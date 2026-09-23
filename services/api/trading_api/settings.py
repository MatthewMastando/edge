"""Environment-driven settings. Every variable is documented in `.env.example`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RuntimeMode = Literal["fixture", "live"]


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    mode: RuntimeMode = Field(default="fixture", alias="TRW_MODE")
    environment: str = Field(default="development", alias="TRW_ENV")
    log_level: str = Field(default="INFO", alias="TRW_LOG_LEVEL")
    display_timezone: str = Field(default="America/New_York", alias="TRW_DISPLAY_TIMEZONE")

    database_url: str = Field(
        default="postgresql://postgres:postgres@127.0.0.1:54322/postgres", alias="DATABASE_URL"
    )

    supabase_url: str = Field(default="http://127.0.0.1:54321", alias="SUPABASE_URL")
    supabase_anon_key: str = Field(default="", alias="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(default="", alias="SUPABASE_SERVICE_ROLE_KEY")
    supabase_jwt_secret: str = Field(default="", alias="SUPABASE_JWT_SECRET")
    supabase_storage_bucket: str = Field(
        default="market-snapshots", alias="SUPABASE_STORAGE_BUCKET"
    )

    storage_backend: Literal["local", "supabase"] = Field(
        default="local", alias="TRW_STORAGE_BACKEND"
    )
    storage_root: Path = Field(default=Path(".data/parquet"), alias="TRW_STORAGE_ROOT")
    fixtures_root: Path = Field(default=Path("fixtures/generated"), alias="TRW_FIXTURES_ROOT")

    host: str = Field(default="127.0.0.1", alias="API_HOST")
    port: int = Field(default=8000, alias="API_PORT")
    cors_origins: str = Field(
        default="http://127.0.0.1:5173,http://localhost:5173", alias="API_CORS_ORIGINS"
    )

    llm_provider: Literal["recorded", "openai"] = Field(default="recorded", alias="LLM_PROVIDER")
    llm_recordings_root: Path = Field(
        default=Path("fixtures/recorded"), alias="LLM_RECORDINGS_ROOT"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def redacted(self) -> dict[str, str]:
        """Safe-to-log view. Secrets never appear in logs or model context."""
        return {
            "mode": self.mode,
            "environment": self.environment,
            "storage_backend": self.storage_backend,
            "fixtures_root": str(self.fixtures_root),
            "llm_provider": self.llm_provider,
            "database": "configured" if self.database_url else "missing",
            "supabase_jwt_secret": "set" if self.supabase_jwt_secret else "unset",
        }


@lru_cache(maxsize=1)
def get_settings() -> ApiSettings:
    return ApiSettings()
