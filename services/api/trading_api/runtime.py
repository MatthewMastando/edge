"""Shared research dependencies for chat and any other route that runs a job inline."""

from __future__ import annotations

from trading_api.settings import ApiSettings
from trading_core.data.factory import market_config_from_values, select_market_adapter
from trading_core.data.fixture import FixtureAdapter
from trading_core.harness.deps import WorkflowDeps
from trading_core.harness.factory import load_detectors, load_model_provider
from trading_core.harness.limits import ResearchLimits
from trading_core.harness.secrets import secrets_from_environ
from trading_core.research.factory import build_research_services, research_config_from_values
from trading_core.storage.db import Database
from trading_core.storage.local import LocalParquetStore


def research_limits(settings: ApiSettings) -> ResearchLimits:
    return ResearchLimits(
        max_external_retrievals=settings.max_external_retrievals,
        max_evidence_tokens=settings.max_evidence_tokens,
        max_model_iterations=settings.max_model_iterations,
        max_repair_attempts=settings.max_repair_attempts,
        timeout_seconds=settings.timeout_seconds,
        monthly_ai_search_usd=settings.monthly_ai_search_usd,
        monthly_market_data_usd=settings.monthly_market_data_usd,
        llm_reserve_usd=settings.llm_reserve_usd,
        retrieval_reserve_usd=settings.retrieval_reserve_usd,
    )


def workflow_deps(
    *,
    settings: ApiSettings,
    database: Database,
    adapter: FixtureAdapter,
    worker_id: str,
) -> WorkflowDeps:
    market = market_config_from_values(
        futures=settings.market_data_futures,
        equities=settings.market_data_equities,
        crypto=settings.market_data_crypto,
        databento_api_key=settings.databento_api_key,
        alpaca_key_id=settings.alpaca_key_id,
        alpaca_secret=settings.alpaca_secret,
        alpaca_feed=settings.alpaca_feed,
    )
    research = build_research_services(
        research_config_from_values(
            search_provider=settings.search_provider,
            tavily_api_key=settings.tavily_api_key,
            fred_api_key=settings.fred_api_key,
            eia_api_key=settings.eia_api_key,
            nass_api_key=settings.nass_api_key,
            sec_user_agent=settings.sec_user_agent,
            domain_allow=settings.research_domain_allow,
            domain_deny=settings.research_domain_deny,
            max_bytes=settings.fetch_max_bytes,
            timeout_seconds=settings.fetch_timeout_seconds,
        )
    )
    return WorkflowDeps(
        engine=database.engine,
        adapter=select_market_adapter(market, fixture=adapter),
        provider=load_model_provider(
            provider=settings.llm_provider,
            recordings_root=settings.llm_recordings_root,
            model=settings.llm_model or None,
            api_key=settings.openai_api_key,
        ),
        store=LocalParquetStore(settings.storage_root),
        detectors=load_detectors(),
        limits=research_limits(settings),
        worker_id=worker_id,
        lease_seconds=max(int(settings.timeout_seconds), 60),
        model=settings.llm_model or None,
        secrets=secrets_from_environ(),
        research=research,
    )
