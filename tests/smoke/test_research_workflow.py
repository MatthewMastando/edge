"""Database-backed research workflow, leases and the chat/artifact API."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from tests.conftest import FIXTURES_DIR, REPO_ROOT
from trading_api.auth import LOCAL_DEV_USER_ID
from trading_api.main import create_app
from trading_api.settings import ApiSettings
from trading_core.data.fixture import FixtureAdapter
from trading_core.domain.jobs import Job
from trading_core.domain.thesis import Thesis
from trading_core.harness.annotations import annotation_id_for, calculations_from_rows
from trading_core.harness.budget import BudgetExceededError, BudgetService
from trading_core.harness.checkpoints import ResearchCheckpoint
from trading_core.harness.deps import AfterStage, ResearchPayload, WorkflowDeps
from trading_core.harness.errors import SuspendWorkflowError
from trading_core.harness.factory import load_detectors, load_model_provider
from trading_core.harness.limits import ResearchLimits
from trading_core.harness.runner import run_leased_job
from trading_core.harness.validation import validate_thesis
from trading_core.storage.db import Database, fetch_one
from trading_core.storage.local import LocalParquetStore
from trading_core.storage.repositories import analytics, jobs, market
from trading_core.storage.repositories.common import as_int
from trading_worker.main import build_worker
from trading_worker.settings import WorkerSettings

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from apply_migrations import apply_migrations

pytestmark = pytest.mark.postgres


def _postgres_url(conninfo: str) -> str:
    """Turn a libpq keyword conninfo into a SQLAlchemy URL."""
    params = psycopg.conninfo.conninfo_to_dict(conninfo)
    user = params.get("user") or "postgres"
    password = params.get("password") or ""
    host = params.get("host") or "127.0.0.1"
    port = params.get("port") or 5432
    dbname = params.get("dbname") or "postgres"
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


OWNER = LOCAL_DEV_USER_ID


@pytest.fixture(scope="module")
def research_db(database_url: str) -> Iterator[str]:
    name = f"trw_research_{uuid.uuid4().hex[:12]}"
    admin = psycopg.connect(database_url, autocommit=True)
    admin.execute(f'create database "{name}"')
    target = psycopg.conninfo.make_conninfo(database_url, dbname=name)
    apply_migrations(target, seed=True, quiet=True)
    try:
        yield _postgres_url(target)
    finally:
        admin.execute(f'drop database "{name}" with (force)')
        admin.close()


@pytest.fixture
async def engine(research_db: str) -> AsyncIterator[AsyncEngine]:
    database = Database(research_db)
    try:
        yield database.engine
    finally:
        await database.dispose()


def _limits(**overrides: object) -> ResearchLimits:
    values: dict[str, object] = {
        "max_external_retrievals": 12,
        "max_evidence_tokens": 25_000,
        "max_model_iterations": 6,
        "max_repair_attempts": 1,
        "timeout_seconds": 180,
        "monthly_ai_search_usd": "100",
        "llm_reserve_usd": "0.02",
        "retrieval_reserve_usd": "0.01",
    }
    values.update(overrides)
    return ResearchLimits.model_validate(values)


def _json_payload(payload: ResearchPayload) -> dict[str, JsonValue]:
    return cast("dict[str, JsonValue]", payload.model_dump(mode="json"))


def _deps(
    db_engine: AsyncEngine,
    generated_dir: Path,
    tmp_path: Path,
    *,
    worker_id: str = "test-worker",
    limits: ResearchLimits | None = None,
    after_stage: AfterStage | None = None,
) -> WorkflowDeps:
    deps = WorkflowDeps(
        engine=db_engine,
        adapter=FixtureAdapter(generated_dir),
        provider=load_model_provider(
            provider="recorded",
            recordings_root=FIXTURES_DIR / "recorded",
            model=None,
        ),
        store=LocalParquetStore(tmp_path / worker_id),
        detectors=load_detectors(),
        limits=limits or _limits(),
        worker_id=worker_id,
        lease_seconds=60,
        secrets=("super-secret-token",),
    )
    deps.after_stage = after_stage
    return deps


async def _enqueue(engine: AsyncEngine, *, symbol: str = "6EZ6", key: str | None = None) -> Job:
    payload = ResearchPayload(
        symbol=symbol,
        question=f"What is the evidence for {symbol}?",
        owner_id=OWNER,
    )
    async with engine.begin() as conn:
        return await jobs.enqueue_job(
            conn,
            kind="research",
            idempotency_key=key or f"research-{uuid.uuid4()}",
            payload=_json_payload(payload),
            conversation_id=None,
            priority=10,
        )


async def test_skip_locked_leases_distinct_jobs_and_partial_is_leasable(
    engine: AsyncEngine,
) -> None:
    first = await _enqueue(engine, key=f"lease-a-{uuid.uuid4()}")
    second = await _enqueue(engine, key=f"lease-b-{uuid.uuid4()}")
    left = await engine.connect()
    right = await engine.connect()
    await left.begin()
    leased = await jobs.lease_next(left, worker_id="w1", lease_seconds=30, kinds=["research"])
    await right.begin()
    other = await jobs.lease_next(right, worker_id="w2", lease_seconds=30, kinds=["research"])
    await right.commit()
    await left.commit()
    await right.close()
    await left.close()
    assert leased is not None and leased.id in {first.id, second.id}
    assert other is not None and other.id != leased.id
    async with engine.begin() as conn:
        paused = await jobs.set_state(
            conn,
            job_id=leased.id,
            worker_id="w1",
            state="partial",
            checkpoint=leased.checkpoint,
            last_error="paused",
        )
    assert paused is not None
    assert paused.state == "partial"
    assert paused.lease_until is None and paused.leased_by is None
    async with engine.begin() as conn:
        again = await jobs.lease_job(conn, job_id=paused.id, worker_id="w3", lease_seconds=30)
    assert again is not None and again.state == "running" and again.id == paused.id


async def test_extended_lease_is_not_requeued(engine: AsyncEngine) -> None:
    held = await _enqueue(engine, key=f"hold-{uuid.uuid4()}")
    dropped = await _enqueue(engine, key=f"drop-{uuid.uuid4()}")
    async with engine.begin() as conn:
        assert await jobs.lease_job(conn, job_id=held.id, worker_id="holder", lease_seconds=30)
        assert await jobs.lease_job(conn, job_id=dropped.id, worker_id="holder", lease_seconds=30)
    async with engine.begin() as conn:
        for job_id in (held.id, dropped.id):
            await fetch_one(
                conn,
                """
                update jobs
                set lease_until = now() - interval '1 second'
                where id = :id
                returning id
                """,
                {"id": job_id},
            )
        assert await jobs.extend_lease(conn, job_id=held.id, worker_id="holder", lease_seconds=30)
        expired = await jobs.requeue_expired(conn)
        kept = await jobs.get_job(conn, held.id)
        released = await jobs.get_job(conn, dropped.id)
    assert expired == 1
    assert kept is not None and kept.state == "running" and kept.leased_by == "holder"
    assert released is not None and released.state == "queued"
    assert released.lease_until is None and released.leased_by is None


async def test_recorded_workflow_resumes_without_duplicate_artifacts(
    engine: AsyncEngine, generated_dir: Path, tmp_path: Path
) -> None:
    job = await _enqueue(engine, key=f"flow-{uuid.uuid4()}")

    async def pause_after_capture(stage: str, checkpoint: ResearchCheckpoint) -> None:
        del checkpoint
        if stage == "capture_snapshot":
            raise SuspendWorkflowError("test pause")

    deps = _deps(
        engine, generated_dir, tmp_path, worker_id="resume-1", after_stage=pause_after_capture
    )
    async with engine.begin() as conn:
        leased = await jobs.lease_job(conn, job_id=job.id, worker_id="resume-1", lease_seconds=60)
    assert leased is not None
    paused = await run_leased_job(deps, leased)
    assert paused.state == "partial"
    assert paused.lease_until is None

    deps.after_stage = None
    deps.worker_id = "resume-2"
    async with engine.begin() as conn:
        resumed = await jobs.lease_job(conn, job_id=job.id, worker_id="resume-2", lease_seconds=60)
    assert resumed is not None
    finished = await run_leased_job(deps, resumed)
    assert finished.state == "completed"
    thesis = finished.checkpoint.get("thesis")
    assert isinstance(thesis, dict)
    assert thesis.get("is_demonstration") is True
    assert thesis.get("provenance") == "recorded"
    assert "presentation_markdown" in thesis
    stubs = finished.checkpoint.get("stub_detectors")
    assert stubs == []
    await _assert_saved_calculations(engine, finished.checkpoint["thesis"])

    async with engine.begin() as conn:
        revisions = await fetch_one(
            conn,
            "select count(*) as n from artifact_revisions where run_id = :run_id",
            {"run_id": UUID(str(finished.checkpoint["run_id"]))},
        )
        runs = await fetch_one(
            conn, "select count(*) as n from runs where job_id = :job_id", {"job_id": job.id}
        )
        notes = await jobs.count_notifications(conn, f"research:{job.id}:new_research")
    assert revisions is not None and as_int(revisions["n"]) == 1
    assert runs is not None and as_int(runs["n"]) == 1
    # Recorded 6EZ6 thesis is insufficient evidence, so it is not an actionable alert.
    assert notes == 0

    async with engine.begin() as conn:
        third = await jobs.lease_job(conn, job_id=job.id, worker_id="resume-3", lease_seconds=30)
    assert third is None


async def test_lost_lease_during_persist_does_not_keep_a_second_revision(
    engine: AsyncEngine, generated_dir: Path, tmp_path: Path
) -> None:
    """A failed checkpoint save must roll back the revision. Resume writes that one revision."""
    job = await _enqueue(engine, key=f"lease-loss-{uuid.uuid4()}")
    original = jobs.save_checkpoint
    failed = False

    async def fail_the_persist_save(
        conn: AsyncConnection,
        *,
        job_id: UUID,
        worker_id: str,
        checkpoint: dict[str, JsonValue],
        lease_seconds: int,
    ) -> bool:
        nonlocal failed
        if not failed and checkpoint.get("revision_id") is not None:
            failed = True
            return False
        return await original(
            conn,
            job_id=job_id,
            worker_id=worker_id,
            checkpoint=checkpoint,
            lease_seconds=lease_seconds,
        )

    jobs.save_checkpoint = fail_the_persist_save
    try:
        deps = _deps(engine, generated_dir, tmp_path, worker_id="lease-loss")
        async with engine.begin() as conn:
            leased = await jobs.lease_job(
                conn, job_id=job.id, worker_id="lease-loss", lease_seconds=60
            )
        assert leased is not None
        stopped = await run_leased_job(deps, leased)
    finally:
        jobs.save_checkpoint = original

    assert failed is True
    assert stopped.state == "running"
    assert stopped.checkpoint.get("revision_id") is None
    run_id = UUID(str(stopped.checkpoint["run_id"]))
    async with engine.begin() as conn:
        revisions = await fetch_one(
            conn,
            "select count(*) as n from artifact_revisions where run_id = :run_id",
            {"run_id": run_id},
        )
        runs = await fetch_one(
            conn, "select count(*) as n from runs where job_id = :job_id", {"job_id": job.id}
        )
        released = await jobs.set_state(
            conn,
            job_id=job.id,
            worker_id="lease-loss",
            state="partial",
            checkpoint=stopped.checkpoint,
            last_error="lease lost during persist",
        )
    assert revisions is not None and as_int(revisions["n"]) == 0
    assert runs is not None and as_int(runs["n"]) == 1
    assert released is not None and released.state == "partial"

    deps.worker_id = "lease-resume"
    async with engine.begin() as conn:
        resumed = await jobs.lease_job(
            conn, job_id=job.id, worker_id="lease-resume", lease_seconds=60
        )
    assert resumed is not None
    finished = await run_leased_job(deps, resumed)
    assert finished.state == "completed"
    assert finished.checkpoint.get("run_id") == str(run_id)
    await _assert_saved_calculations(engine, finished.checkpoint["thesis"])
    async with engine.begin() as conn:
        revisions = await fetch_one(
            conn,
            "select count(*) as n from artifact_revisions where run_id = :run_id",
            {"run_id": run_id},
        )
        runs = await fetch_one(
            conn, "select count(*) as n from runs where job_id = :job_id", {"job_id": job.id}
        )
        notes = await jobs.count_notifications(conn, f"research:{job.id}:new_research")
    assert revisions is not None and as_int(revisions["n"]) == 1
    assert runs is not None and as_int(runs["n"]) == 1
    assert notes == 0


async def test_budget_ceiling_stops_the_run(
    engine: AsyncEngine, generated_dir: Path, tmp_path: Path
) -> None:
    job = await _enqueue(engine, key=f"budget-{uuid.uuid4()}")
    deps = _deps(
        engine,
        generated_dir,
        tmp_path,
        worker_id="budget-worker",
        limits=_limits(monthly_ai_search_usd="0"),
    )
    async with engine.begin() as conn:
        leased = await jobs.lease_job(
            conn, job_id=job.id, worker_id="budget-worker", lease_seconds=60
        )
    assert leased is not None
    finished = await run_leased_job(deps, leased)
    assert finished.state == "budget_exceeded"
    async with engine.begin() as conn:
        row = await fetch_one(
            conn,
            "select kind from notifications where dedupe_key = :key",
            {"key": f"budget:{job.id}"},
        )
    assert row is not None and row["kind"] == "budget"


async def test_evidence_cap_returns_partial_once(
    engine: AsyncEngine, generated_dir: Path, tmp_path: Path
) -> None:
    job = await _enqueue(engine, key=f"tokens-{uuid.uuid4()}")
    deps = _deps(
        engine,
        generated_dir,
        tmp_path,
        worker_id="token-worker",
        limits=_limits(max_evidence_tokens=1),
    )
    async with engine.begin() as conn:
        leased = await jobs.lease_job(
            conn, job_id=job.id, worker_id="token-worker", lease_seconds=60
        )
    assert leased is not None
    finished = await run_leased_job(deps, leased)
    assert finished.state == "completed"
    assert finished.checkpoint.get("partial_research") is True
    assert finished.checkpoint.get("stop_reason") == "evidence_token_cap"
    thesis = finished.checkpoint.get("thesis")
    assert isinstance(thesis, dict)
    assert thesis.get("is_demonstration") is True
    assert thesis.get("provenance") == "recorded"
    run_id = UUID(str(finished.checkpoint["run_id"]))
    async with engine.begin() as conn:
        run = await jobs.get_run(conn, run_id)
        revisions = await fetch_one(
            conn,
            "select count(*) as n from artifact_revisions where run_id = :run_id",
            {"run_id": run_id},
        )
        notes = await jobs.count_notifications(conn, f"research:{job.id}:new_research")
        again = await jobs.lease_job(
            conn, job_id=job.id, worker_id="token-worker", lease_seconds=30
        )
    assert run is not None and run.status == "partial"
    assert revisions is not None and as_int(revisions["n"]) == 1
    assert notes == 0
    assert again is None


async def test_budget_lock_serializes_reserves(engine: AsyncEngine) -> None:
    job = await _enqueue(engine, key=f"lock-{uuid.uuid4()}")
    async with engine.begin() as conn:
        run = await jobs.insert_run(
            conn,
            job_id=job.id,
            conversation_id=None,
            provider="recorded",
            provenance="recorded",
            model=None,
            prompt_version="test",
        )
    limits = _limits(monthly_ai_search_usd="0.03")
    budget = BudgetService(engine, limits, run_id=run.id, job_id=job.id)
    start, _end = analytics.month_bounds(datetime.now(UTC))
    started = asyncio.Event()
    release = asyncio.Event()

    async def hold_budget_row() -> None:
        async with engine.begin() as conn:
            await analytics.upsert_budget(
                conn,
                category="ai_search",
                period_start=start,
                limit_usd=Decimal("0.03"),
            )
            started.set()
            await release.wait()

    async def reserve_once() -> str:
        await started.wait()
        await asyncio.sleep(0.05)
        try:
            await budget.reserve(
                category="search",
                provider="fixture",
                estimate=Decimal("0.02"),
                unit_type="calls",
            )
        except BudgetExceededError:
            return "stopped"
        return "reserved"

    holder = asyncio.create_task(hold_budget_row())
    challenger: asyncio.Task[str] | None = None
    try:
        await started.wait()
        challenger = asyncio.create_task(reserve_once())
        await asyncio.sleep(0.15)
        assert not challenger.done()
        release.set()
        await holder
        assert await challenger == "reserved"
    finally:
        release.set()
        if not holder.done():
            holder.cancel()
        if challenger is not None and not challenger.done():
            challenger.cancel()
    try:
        await budget.reserve(
            category="search",
            provider="fixture",
            estimate=Decimal("0.02"),
            unit_type="calls",
        )
    except BudgetExceededError:
        return
    msg = "second reserve passed the monthly ceiling"
    raise AssertionError(msg)


async def test_chat_streams_progress_and_drafts_do_not_rewrite_revisions(
    research_db: str, generated_dir: Path, tmp_path: Path
) -> None:
    settings = ApiSettings(
        mode="fixture",
        fixtures_root=generated_dir,
        database_url=research_db,
        storage_root=tmp_path / "api-parquet",
        llm_recordings_root=FIXTURES_DIR / "recorded",
        supabase_jwt_secret="",
    )
    with TestClient(create_app(settings)) as http:
        first = http.post(
            "/v1/chat",
            json={"message": "Research 6EZ6", "symbol": "6EZ6", "client_message_id": "msg-1"},
        )
        assert first.status_code == 200
        body = first.text
        assert "event: progress" in body
        assert "event: message" in body
        assert "event: done" in body
        assert "is_demonstration" in body
        conversation_id = _conversation_id(body)

        retry = http.post(
            "/v1/chat",
            json={
                "message": "Research 6EZ6",
                "symbol": "6EZ6",
                "client_message_id": "msg-1",
                "conversation_id": conversation_id,
            },
        )
        assert retry.status_code == 200
        assert "not started again" in retry.text

        runs = http.get("/v1/runs")
        assert runs.status_code == 200
        assert len(runs.json()) == 1
        run_id = runs.json()[0]["id"]
        events = http.get(f"/v1/runs/{run_id}/events")
        assert events.status_code == 200
        assert events.json()

        artifacts = http.get("/v1/artifacts")
        assert artifacts.status_code == 200
        revision_id = runs.json()[0]["artifact_revision_id"]
        [artifact] = [
            item for item in artifacts.json() if item["current_revision_id"] == revision_id
        ]
        revisions = http.get(f"/v1/artifacts/{artifact['id']}/revisions")
        assert revisions.status_code == 200
        [revision] = revisions.json()
        assert revision["is_demonstration"] is True
        detail = http.get(f"/v1/artifacts/{artifact['id']}/revisions/{revision['id']}")
        assert detail.status_code == 200
        structured = detail.json()["structured"]
        assert structured["stance"] == "insufficient_evidence"
        assert structured["presentation_markdown"] != ""
        assert "Demonstration" in detail.json()["presentation_markdown"]
        assert "fvg 1.0.0" in detail.json()["presentation_markdown"]
        database = Database(research_db)
        try:
            await _assert_saved_calculations(database.engine, structured)
        finally:
            await database.dispose()

        saved = http.put(
            f"/v1/artifacts/{artifact['id']}/draft",
            json={
                "base_revision_id": revision["id"],
                "presentation_markdown": "Autosaved note. Not a new revision.",
            },
        )
        assert saved.status_code == 200
        draft = http.get(f"/v1/artifacts/{artifact['id']}/draft")
        assert draft.json()["presentation_markdown"].startswith("Autosaved")
        still = http.get(f"/v1/artifacts/{artifact['id']}/revisions")
        assert len(still.json()) == 1

        found = http.get("/v1/search", params={"q": "6EZ6"})
        assert found.status_code == 200
        assert found.json()["artifacts"]
        assert found.json()["conversations"]


def test_worker_dispatch_streams_until_the_worker_finishes(
    research_db: str, generated_dir: Path, tmp_path: Path
) -> None:
    settings = ApiSettings(
        mode="fixture",
        fixtures_root=generated_dir,
        database_url=research_db,
        storage_root=tmp_path / "dispatch-api",
        llm_recordings_root=FIXTURES_DIR / "recorded",
        supabase_jwt_secret="",
        timeout_seconds=120,
    )
    worker = build_worker(
        WorkerSettings(
            database_url=research_db,
            fixtures_root=generated_dir,
            llm_recordings_root=FIXTURES_DIR / "recorded",
            storage_root=tmp_path / "dispatch-worker",
            worker_id="dispatch-worker",
        )
    )
    box: dict[str, object] = {}

    def post() -> None:
        try:
            with TestClient(create_app(settings)) as http:
                response = http.post(
                    "/v1/chat",
                    json={
                        "message": "Research 6EZ6 on the fixture path.",
                        "symbol": "6EZ6",
                        "client_message_id": f"worker-{uuid.uuid4().hex[:8]}",
                        "dispatch": "worker",
                    },
                )
                box["status"] = response.status_code
                box["text"] = response.text
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(target=post)
    thread.start()
    deadline = time.monotonic() + 20

    async def wait_and_run() -> None:
        database = Database(research_db)
        try:
            row: dict[str, object] | None = None
            while time.monotonic() < deadline:
                async with database.engine.begin() as conn:
                    row = await fetch_one(
                        conn,
                        """
                        select id from jobs
                        where state = 'queued'
                          and kind = 'research'
                          and payload->>'question' = 'Research 6EZ6 on the fixture path.'
                        order by created_at desc
                        limit 1
                        """,
                    )
                if row is not None:
                    break
                await asyncio.sleep(0.05)
            else:
                msg = "worker dispatch did not enqueue a job"
                raise AssertionError(msg)
            job_id = row["id"]
            if not isinstance(job_id, UUID):
                msg = "queued job id was not a UUID"
                raise AssertionError(msg)
            async with database.engine.begin() as conn:
                leased = await jobs.lease_job(
                    conn,
                    job_id=job_id,
                    worker_id="dispatch-worker",
                    lease_seconds=120,
                )
            if leased is None:
                msg = "worker dispatch job could not be leased"
                raise AssertionError(msg)
            await worker.run_leased(leased)
        finally:
            await database.dispose()
            await worker.close()

    asyncio.run(wait_and_run())
    thread.join(30)
    assert not thread.is_alive()
    assert box.get("error") is None
    assert box.get("status") == 200
    body = box.get("text")
    assert isinstance(body, str)
    assert "event: progress" in body
    assert "deterministic_ta" in body
    assert "event: done" in body
    assert "artifact_id" in body


def test_worker_once_drains_a_queued_research_job(
    research_db: str, generated_dir: Path, tmp_path: Path
) -> None:
    settings = WorkerSettings(
        database_url=research_db,
        fixtures_root=generated_dir,
        llm_recordings_root=FIXTURES_DIR / "recorded",
        storage_root=tmp_path / "worker-parquet",
        worker_id="once-worker",
    )
    worker = build_worker(settings)
    database = Database(research_db)

    async def scenario() -> str:
        payload = ResearchPayload(symbol="6EZ6", question="Worker path for 6EZ6", owner_id=OWNER)
        async with database.engine.begin() as conn:
            job = await jobs.enqueue_job(
                conn,
                kind="research",
                idempotency_key=f"worker-{uuid.uuid4()}",
                payload=_json_payload(payload),
                priority=20,
            )
        processed = await worker.poll_once()
        assert processed == 1
        async with database.engine.begin() as conn:
            stored = await jobs.get_job(conn, job.id)
        assert stored is not None and stored.state == "completed"
        await _assert_saved_calculations(database.engine, stored.checkpoint["thesis"])
        await database.dispose()
        await worker.close()
        return stored.state

    assert asyncio.run(scenario()) == "completed"


async def _assert_saved_calculations(engine: AsyncEngine, thesis_raw: object) -> None:
    """Reopened thesis figures and chart annotations are the saved calc 1.0.0 features."""
    thesis = Thesis.model_validate(thesis_raw)
    assert thesis.is_demonstration is True
    assert thesis.provenance == "recorded"
    assert thesis.validation.passed is True
    assert thesis.validation.repair_attempted is False
    assert thesis.technical_findings
    for name in (
        "volume_profile",
        "fvg",
        "liquidity_sweep",
        "bos",
        "order_block",
        "rsi_divergence",
    ):
        assert thesis.versions.tool_versions.get(name) == "1.0.0"
    feature_ids = [item.feature_id for item in thesis.technical_findings]
    async with engine.begin() as conn:
        rows = await market.feature_calculation_rows(conn, feature_ids)
        levels = await market.feature_levels(conn, feature_ids)
        known = await market.list_feature_ids(conn, feature_ids)
        events = await fetch_one(
            conn,
            "select count(*) as n from ta_events where feature_id = any(cast(string_to_array(:ids, ',') as uuid[]))",
            {"ids": ",".join(str(item) for item in feature_ids)},
        )
    calculations = calculations_from_rows(rows)
    assert set(calculations) == set(feature_ids)
    assert len(rows) == len(set(feature_ids))
    assert events is not None and as_int(events["n"]) > 0
    for finding in thesis.technical_findings:
        saved = calculations[finding.feature_id]
        assert finding.annotation_id == annotation_id_for(finding.feature_id)
        assert saved.annotation.id == finding.annotation_id
        assert {level.price for level in saved.annotation.levels} == levels[finding.feature_id]
        assert saved.calc_version == "1.0.0"
    unsupported = thesis.model_copy(
        update={"plan": thesis.plan.model_copy(update={"entry": Decimal("999999")})}
    )
    failed = validate_thesis(
        unsupported,
        known_feature_ids=known,
        feature_levels=levels,
        known_source_ids=set(),
        known_excerpt_ids=set(),
        tick_value=None,
        point_value=None,
        calculations=calculations,
    )
    assert failed.passed is False
    numeric = next(check for check in failed.checks if check.name == "numeric_crosscheck")
    assert numeric.passed is False


def _conversation_id(body: str) -> str:
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = json.loads(line.removeprefix("data: "))
        if isinstance(payload, dict) and payload.get("conversation_id"):
            value = payload["conversation_id"]
            if isinstance(value, str):
                return value
    msg = "chat stream did not include a conversation id"
    raise AssertionError(msg)
