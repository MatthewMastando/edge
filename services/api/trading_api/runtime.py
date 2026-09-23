"""Shared research dependencies for chat and any other route that runs a job inline."""

from __future__ import annotations

from trading_api.settings import ApiSettings
from trading_core.data.fixture import FixtureAdapter
from trading_core.harness.deps import WorkflowDeps
from trading_core.harness.factory import load_model_provider
from trading_core.harness.limits import ResearchLimits
from trading_core.harness.secrets import secrets_from_environ
from trading_core.storage.db import Database
from trading_core.storage.local import LocalParquetStore
from trading_core.ta import DetectorRegistry


def research_limits(settings: ApiSettings) -> ResearchLimits:
    return ResearchLimits(
        max_external_retrievals=settings.max_external_retrievals,
        max_evidence_tokens=settings.max_evidence_tokens,
        max_model_iterations=settings.max_model_iterations,
        max_repair_attempts=settings.max_repair_attempts,
        timeout_seconds=settings.timeout_seconds,
        monthly_ai_search_usd=settings.monthly_ai_search_usd,
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
    return WorkflowDeps(
        engine=database.engine,
        adapter=adapter,
        provider=load_model_provider(
            provider=settings.llm_provider,
            recordings_root=settings.llm_recordings_root,
            model=settings.llm_model or None,
        ),
        store=LocalParquetStore(settings.storage_root),
        detectors=DetectorRegistry(),
        limits=research_limits(settings),
        worker_id=worker_id,
        lease_seconds=max(int(settings.timeout_seconds), 60),
        model=settings.llm_model or None,
        secrets=secrets_from_environ(),
    )
