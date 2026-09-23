from __future__ import annotations

import socket
from decimal import Decimal
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
    llm_model: str = Field(default="", alias="OPENAI_MODEL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    market_data_futures: str = Field(default="fixture", alias="MARKET_DATA_FUTURES")
    market_data_equities: str = Field(default="fixture", alias="MARKET_DATA_EQUITIES")
    market_data_crypto: str = Field(default="fixture", alias="MARKET_DATA_CRYPTO")
    databento_api_key: str = Field(default="", alias="DATABENTO_API_KEY")
    alpaca_key_id: str = Field(default="", alias="ALPACA_API_KEY_ID")
    alpaca_secret: str = Field(default="", alias="ALPACA_API_SECRET_KEY")
    alpaca_feed: str = Field(default="iex", alias="ALPACA_DATA_FEED")
    search_provider: str = Field(default="fixture", alias="SEARCH_PROVIDER")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    fred_api_key: str = Field(default="", alias="FRED_API_KEY")
    eia_api_key: str = Field(default="", alias="EIA_API_KEY")
    nass_api_key: str = Field(default="", alias="USDA_NASS_API_KEY")
    sec_user_agent: str = Field(default="", alias="SEC_EDGAR_USER_AGENT")
    research_domain_allow: str = Field(default="", alias="RESEARCH_DOMAIN_ALLOW")
    research_domain_deny: str = Field(default="", alias="RESEARCH_DOMAIN_DENY")
    fetch_max_bytes: int = Field(default=1_000_000, alias="RESEARCH_FETCH_MAX_BYTES", ge=1)
    fetch_timeout_seconds: float = Field(default=10, alias="RESEARCH_FETCH_TIMEOUT_SECONDS", gt=0)
    storage_root: Path = Field(default=Path(".data/parquet"), alias="TRW_STORAGE_ROOT")
    max_external_retrievals: int = Field(default=12, alias="RESEARCH_MAX_RETRIEVALS", ge=0)
    max_evidence_tokens: int = Field(default=25_000, alias="RESEARCH_MAX_EVIDENCE_TOKENS", ge=1)
    max_model_iterations: int = Field(default=6, alias="RESEARCH_MAX_ITERATIONS", ge=1)
    max_repair_attempts: int = Field(default=1, alias="RESEARCH_MAX_REPAIRS", ge=0, le=1)
    timeout_seconds: float = Field(default=180, alias="RESEARCH_TIMEOUT_SECONDS", ge=0)
    monthly_ai_search_usd: Decimal = Field(
        default=Decimal("100"), alias="BUDGET_AI_SEARCH_MONTHLY_USD"
    )
    monthly_market_data_usd: Decimal = Field(
        default=Decimal("0"), alias="BUDGET_MARKET_DATA_MONTHLY_USD"
    )
    llm_reserve_usd: Decimal = Field(default=Decimal("0.02"), alias="RESEARCH_LLM_RESERVE_USD")
    retrieval_reserve_usd: Decimal = Field(
        default=Decimal("0.01"), alias="RESEARCH_RETRIEVAL_RESERVE_USD"
    )

    @property
    def effective_worker_id(self) -> str:
        return self.worker_id or f"{socket.gethostname()}-{id(self) & 0xFFFF:04x}"

    @property
    def effective_lease_seconds(self) -> int:
        """Cover a full research timeout so a second worker cannot steal an in-flight job."""
        return max(self.lease_seconds, int(self.timeout_seconds))


@lru_cache(maxsize=1)
def get_settings() -> WorkerSettings:
    return WorkerSettings()
