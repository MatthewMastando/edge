"""Worker entrypoint.

Leases queued and partial jobs with ``FOR UPDATE SKIP LOCKED``, then runs the checkpointed
research workflow. A paused job has no lease, so the next poll can resume it.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from trading_core.automation.dispatch import dispatch_due, evaluate_triggers
from trading_core.automation.hypotheses import observe_open
from trading_core.automation.scan import run_scan
from trading_core.data.fixture import FixtureAdapter
from trading_core.harness.deps import WorkflowDeps
from trading_core.harness.factory import load_detectors, load_model_provider
from trading_core.harness.limits import ResearchLimits
from trading_core.harness.runner import run_leased_job
from trading_core.harness.secrets import secrets_from_environ
from trading_core.storage.db import Database
from trading_core.storage.local import LocalParquetStore
from trading_core.storage.repositories import jobs
from trading_worker import __version__
from trading_worker.settings import WorkerSettings, get_settings

if TYPE_CHECKING:
    from trading_core.domain.jobs import Job, JobKind

log = logging.getLogger("trading_worker")


class JobHandler(Protocol):
    """Runs one job kind. Implementations must be idempotent per ``job.idempotency_key`` and
    resume from ``job.checkpoint``."""

    @property
    def kind(self) -> JobKind: ...

    async def run(self, job: Job) -> None: ...


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, handler: JobHandler) -> None:
        if handler.kind in self._handlers:
            msg = f"handler already registered for {handler.kind}"
            raise ValueError(msg)
        self._handlers[handler.kind] = handler

    def get(self, kind: str) -> JobHandler | None:
        return self._handlers.get(kind)

    def kinds(self) -> list[str]:
        return sorted(self._handlers)


class ResearchJobHandler:
    def __init__(self, deps: WorkflowDeps, *, kind: JobKind = "research") -> None:
        self._deps = deps
        self._kind = kind

    @property
    def kind(self) -> JobKind:
        return self._kind

    async def run(self, job: Job) -> None:
        await run_leased_job(self._deps, job)


class TaScanJobHandler:
    def __init__(self, deps: WorkflowDeps) -> None:
        self._deps = deps

    @property
    def kind(self) -> JobKind:
        return "ta_scan"

    async def run(self, job: Job) -> None:
        await run_scan(self._deps, job)
        async with self._deps.engine.begin() as conn:
            await evaluate_triggers(conn, now=datetime.now(UTC))


class HypothesisJobHandler:
    def __init__(self, deps: WorkflowDeps) -> None:
        self._deps = deps

    @property
    def kind(self) -> JobKind:
        return "hypothesis_check"

    async def run(self, job: Job) -> None:
        try:
            async with self._deps.engine.begin() as conn:
                await observe_open(conn, self._deps.adapter)
                await jobs.set_state(
                    conn,
                    job_id=job.id,
                    worker_id=self._deps.worker_id,
                    state="completed",
                    checkpoint={"observed": True},
                    last_error=None,
                )
        except Exception as exc:
            log.error("hypothesis check %s failed: %s", job.id, exc)
            async with self._deps.engine.begin() as conn:
                await jobs.set_state(
                    conn,
                    job_id=job.id,
                    worker_id=self._deps.worker_id,
                    state="failed",
                    checkpoint={},
                    last_error=str(exc)[:500],
                )


class Worker:
    def __init__(
        self,
        settings: WorkerSettings,
        registry: HandlerRegistry,
        database: Database | None,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._database = database
        self._stop = asyncio.Event()
        self.iterations = 0

    def request_stop(self) -> None:
        self._stop.set()

    async def run_leased(self, job: Job) -> None:
        """Run one job that the caller already leased. Does not scan the queue."""
        handler = self._registry.get(job.kind)
        if handler is None:
            msg = f"no handler registered for {job.kind}"
            raise RuntimeError(msg)
        await handler.run(job)

    async def poll_once(self) -> int:
        """Lease and run at most one job. Returns 1 when a job was taken."""
        self.iterations += 1
        kinds = self._registry.kinds()
        if self._database is None or not kinds:
            log.debug("no handlers registered; idle")
            return 0
        async with self._database.engine.begin() as conn:
            expired = await jobs.requeue_expired(conn)
            if expired:
                log.info("requeued %d expired lease(s)", expired)
            scheduled = await dispatch_due(conn, now=datetime.now(UTC))
            if scheduled:
                log.info("enqueued %d automation job(s)", scheduled)
            job = await jobs.lease_next(
                conn,
                worker_id=self._settings.effective_worker_id,
                lease_seconds=self._settings.effective_lease_seconds,
                kinds=kinds,
            )
        if job is None:
            return 0
        handler = self._registry.get(job.kind)
        if handler is None:
            log.error("leased %s but no handler is registered", job.kind)
            return 0
        await handler.run(job)
        return 1

    async def run(self, *, once: bool = False) -> None:
        log.info(
            "trading-worker %s starting (id=%s, mode=%s, handlers=%s)",
            __version__,
            self._settings.effective_worker_id,
            self._settings.mode,
            self._registry.kinds() or "none",
        )
        while not self._stop.is_set():
            processed = await self.poll_once()
            if once:
                break
            if processed == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self._settings.poll_interval_seconds
                    )
        log.info("trading-worker stopped after %d poll(s)", self.iterations)

    async def close(self) -> None:
        if self._database is not None:
            await self._database.dispose()


def _limits(settings: WorkerSettings) -> ResearchLimits:
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


def build_worker(settings: WorkerSettings) -> Worker:
    """Register research when fixture data is present. Missing fixtures idle without a database."""
    registry = HandlerRegistry()
    try:
        adapter = FixtureAdapter(settings.fixtures_root)
    except FileNotFoundError:
        log.warning("fixture manifest not found at %s; worker will idle", settings.fixtures_root)
        return Worker(settings, registry, None)
    database = Database(settings.database_url)
    provider = load_model_provider(
        provider=settings.llm_provider,
        recordings_root=settings.llm_recordings_root,
        model=settings.llm_model or None,
    )
    deps = WorkflowDeps(
        engine=database.engine,
        adapter=adapter,
        provider=provider,
        store=LocalParquetStore(settings.storage_root),
        detectors=load_detectors(),
        limits=_limits(settings),
        worker_id=settings.effective_worker_id,
        lease_seconds=settings.effective_lease_seconds,
        model=settings.llm_model or None,
        secrets=secrets_from_environ(),
    )
    registry.register(ResearchJobHandler(deps))
    registry.register(ResearchJobHandler(deps, kind="scheduled_briefing"))
    registry.register(TaScanJobHandler(deps))
    registry.register(HypothesisJobHandler(deps))
    return Worker(settings, registry, database)


async def _amain(once: bool) -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    worker = build_worker(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.request_stop)
    try:
        await worker.run(once=once)
    finally:
        await worker.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading-worker")
    parser.add_argument("--once", action="store_true", help="poll a single time and exit")
    args = parser.parse_args(argv)
    asyncio.run(_amain(once=bool(args.once)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
