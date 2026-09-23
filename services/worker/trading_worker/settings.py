from __future__ import annotations

import socket
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    mode: Literal["fixture", "live"] = Field(default="fixture", alias="TRW_MODE")
    log_level: str = Field(default="INFO", alias="TRW_LOG_LEVEL")
    database_url: str = Field(
        default="postgresql://postgres:postgres@127.0.0.1:54322/postgres", alias="DATABASE_URL"
    )
    poll_interval_seconds: float = Field(default=2.0, alias="WORKER_POLL_INTERVAL_SECONDS", gt=0)
    lease_seconds: int = Field(default=60, alias="WORKER_LEASE_SECONDS", ge=5)
    worker_id: str = Field(default="", alias="WORKER_ID")
    fixtures_root: Path = Field(default=Path("fixtures/generated"), alias="TRW_FIXTURES_ROOT")
    llm_provider: Literal["recorded", "openai"] = Field(default="recorded", alias="LLM_PROVIDER")
    llm_recordings_root: Path = Field(
        default=Path("fixtures/recorded"), alias="LLM_RECORDINGS_ROOT"
    )

    @property
    def effective_worker_id(self) -> str:
        return self.worker_id or f"{socket.gethostname()}-{id(self) & 0xFFFF:04x}"


@lru_cache(maxsize=1)
def get_settings() -> WorkerSettings:
    return WorkerSettings()
