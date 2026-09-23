"""Database-backed research workflow, leases and the chat/artifact API."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import cast
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import FIXTURES_DIR, REPO_ROOT
from trading_api.auth import LOCAL_DEV_USER_ID
from trading_api.main import create_app
from trading_api.settings import ApiSettings
from trading_core.data.fixture import FixtureAdapter
from trading_core.domain.jobs import Job
from trading_core.harness.checkpoints import ResearchCheckpoint
from trading_core.harness.deps import AfterStage, ResearchPayload, WorkflowDeps
from trading_core.harness.errors import SuspendWorkflowError
from trading_core.harness.factory import load_model_provider
from trading_core.harness.limits import ResearchLimits
from trading_core.harness.runner import run_leased_job
from trading_core.storage.db import Database, fetch_one
from trading_core.storage.local import LocalParquetStore
from trading_core.storage.repositories import jobs
from trading_core.storage.repositories.common import as_int
from trading_core.ta import DetectorRegistry
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
        detectors=DetectorRegistry(),
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
    assert isinstance(stubs, list) and "order_block" in stubs

    async with engine.begin() as conn:
        revisions = await fetch_one(
            conn,
            "select count(*) as n from artifact_revisions where run_id = :run_id",
            {"run_id": UUID(str(finished.checkpoint["run_id"]))},
        )
        runs = await fetch_one(
            conn, "select count(*) as n from runs where job_id = :job_id", {"job_id": job.id}
        )
        notes = await jobs.count_notifications(conn, f"research:{job.id}:result")
    assert revisions is not None and as_int(revisions["n"]) == 1
    assert runs is not None and as_int(runs["n"]) == 1
    assert notes == 1

    async with engine.begin() as conn:
        third = await jobs.lease_job(conn, job_id=job.id, worker_id="resume-3", lease_seconds=30)
    assert third is None


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
        await database.dispose()
        await worker.close()
        return stored.state

    assert asyncio.run(scenario()) == "completed"


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
