"""Postgres coverage for schedules, TA triggers, budgets and the hypothesis ledger."""

from __future__ import annotations

import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import FIXTURES_DIR, REPO_ROOT
from tests.smoke.test_research_workflow import OWNER, _deps, _limits
from trading_api.auth import LOCAL_DEV_USER_ID
from trading_api.main import create_app
from trading_api.settings import ApiSettings
from trading_core.automation.dispatch import dispatch_due, evaluate_triggers
from trading_core.automation.hypotheses import observe_open
from trading_core.data.adapter import BarsRequest
from trading_core.data.fixture import FixtureAdapter
from trading_core.domain.jobs import Usage
from trading_core.harness.budget import BudgetExceededError, BudgetService
from trading_core.harness.deps import ResearchPayload
from trading_core.harness.provider import ModelRequest, ModelResponse, ToolCall
from trading_core.harness.runner import run_leased_job
from trading_core.storage.db import Database, fetch_one
from trading_core.storage.repositories import analytics, jobs
from trading_core.storage.repositories.common import (
    as_datetime,
    as_decimal,
    as_int,
    as_str,
    as_uuid,
)
from trading_worker.main import TaScanJobHandler

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from apply_migrations import apply_migrations

pytestmark = pytest.mark.postgres


def _postgres_url(conninfo: str) -> str:
    params = psycopg.conninfo.conninfo_to_dict(conninfo)
    user = params.get("user") or "postgres"
    password = params.get("password") or ""
    host = params.get("host") or "127.0.0.1"
    port = params.get("port") or 5432
    dbname = params.get("dbname") or "postgres"
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture(scope="module")
def automation_db(database_url: str) -> Iterator[str]:
    name = f"trw_auto_{uuid.uuid4().hex[:12]}"
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
async def engine(automation_db: str) -> AsyncIterator[AsyncEngine]:
    database = Database(automation_db)
    try:
        yield database.engine
    finally:
        await database.dispose()


class _ScriptedProvider:
    """First response asks for a tool. The next reserve is what hits the ceiling."""

    name = "recorded"

    async def respond(self, request: ModelRequest) -> ModelResponse:
        del request
        return ModelResponse(
            response_id="scripted",
            provider="recorded",
            model="scripted",
            provenance="recorded",
            is_demonstration=True,
            output_json={"stance": "bullish", "plan": {"entry": "1.10"}},
            tool_calls=[ToolCall(id="call-1", name="get_quotes", arguments={"symbol": "6EZ6"})],
            finish_reason="tool_calls",
            usage=Usage(actual_cost_usd=Decimal("0.02")),
        )


def _client(db_url: str, generated_dir: Path) -> TestClient:
    settings = ApiSettings(
        mode="fixture",
        fixtures_root=generated_dir,
        database_url=db_url,
        supabase_jwt_secret="",
        llm_recordings_root=FIXTURES_DIR / "recorded",
    )
    return TestClient(create_app(settings))


async def _count(engine: AsyncEngine, sql: str, params: dict[str, object]) -> int:
    async with engine.begin() as conn:
        row = await fetch_one(conn, sql, params)
    assert row is not None
    return as_int(row["n"])


async def test_schedule_survives_restart_without_a_second_artifact(
    engine: AsyncEngine, automation_db: str, generated_dir: Path, tmp_path: Path
) -> None:
    slot = datetime(2026, 9, 23, 12, 30, tzinfo=UTC)
    now = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
    with _client(automation_db, generated_dir) as http:
        created = http.post(
            "/v1/routines",
            json={
                "name": "morning 6E",
                "kind": "scheduled_briefing",
                "schedule_cron": "30 8 * * 1-5",
                "schedule_timezone": "America/New_York",
                "symbols": ["6EZ6"],
                "tier": "full",
                "question": "What changed for 6EZ6?",
            },
        )
        assert created.status_code == 200, created.text
        routine_id = created.json()["id"]
        assert created.json()["next_run_at"].endswith("Z")
        missing = http.post(
            "/v1/routines",
            json={
                "name": "bad",
                "kind": "scheduled_briefing",
                "schedule_cron": "30 8 * * 1-5",
                "symbols": ["NOPE"],
            },
        )
        assert missing.status_code == 404
        invalid = http.post(
            "/v1/routines",
            json={
                "name": "bad cron",
                "kind": "scheduled_briefing",
                "schedule_cron": "not a cron",
                "symbols": ["6EZ6"],
            },
        )
        assert invalid.status_code == 422

    async with engine.begin() as conn:
        await fetch_one(
            conn,
            "update routines set next_run_at = :slot where id = :id returning id",
            {"slot": slot, "id": routine_id},
        )
    left = await engine.connect()
    right = await engine.connect()
    await left.begin()
    await dispatch_due(left, now=now)
    await right.begin()
    await dispatch_due(right, now=now)
    await right.commit()
    await left.commit()
    await right.close()
    await left.close()
    schedules = await _count(
        engine,
        "select count(*) as n from jobs where idempotency_key like :prefix",
        {"prefix": f"schedule:{routine_id}:%"},
    )
    assert schedules == 1
    async with engine.begin() as conn:
        await fetch_one(
            conn,
            "update routines set next_run_at = :slot where id = :id returning id",
            {"slot": slot, "id": routine_id},
        )
        await dispatch_due(conn, now=now)
        job = await jobs.get_job_by_key(conn, f"schedule:{routine_id}:6EZ6:2026-09-23T12:30:00Z")
    assert job is not None
    assert (
        await _count(
            engine,
            "select count(*) as n from jobs where idempotency_key like :prefix",
            {"prefix": f"schedule:{routine_id}:%"},
        )
        == 1
    )
    deps = _deps(engine, generated_dir, tmp_path, worker_id="schedule-worker")
    async with engine.begin() as conn:
        leased = await jobs.lease_job(
            conn, job_id=job.id, worker_id="schedule-worker", lease_seconds=120
        )
    assert leased is not None
    finished = await run_leased_job(deps, leased)
    assert finished.state == "completed"
    revisions = await _count(
        engine,
        "select count(*) as n from artifact_revisions where run_id = :run_id",
        {"run_id": finished.checkpoint["run_id"]},
    )
    assert revisions == 1
    async with engine.begin() as conn:
        await fetch_one(
            conn,
            "update routines set next_run_at = :slot where id = :id returning id",
            {"slot": slot, "id": routine_id},
        )
        await dispatch_due(conn, now=now)
        again = await jobs.lease_job(
            conn, job_id=job.id, worker_id="schedule-worker", lease_seconds=30
        )
    assert again is None
    assert (
        await _count(
            engine,
            "select count(*) as n from artifact_revisions where run_id = :run_id",
            {"run_id": finished.checkpoint["run_id"]},
        )
        == 1
    )


async def test_triggers_record_every_event_and_cap_research_jobs(
    engine: AsyncEngine, automation_db: str, generated_dir: Path, tmp_path: Path
) -> None:
    artifacts_before = await _count(engine, "select count(*) as n from artifacts", {})
    with _client(automation_db, generated_dir) as http:
        created = http.post(
            "/v1/routines",
            json={
                "name": "fvg watch",
                "kind": "ta_trigger",
                "symbols": ["6EZ6"],
                "tier": "brief",
                "timeframe": "5m",
                "daily_cap": 1,
                "cooldown_seconds": 14_400,
                "event_allowlist": [
                    "fvg",
                    "bos",
                    "liquidity_sweep",
                    "order_block",
                    "volume_profile",
                    "rsi_divergence",
                ],
            },
        )
        assert created.status_code == 200, created.text
        empty = http.post(
            "/v1/routines",
            json={"name": "no list", "kind": "ta_trigger", "symbols": ["6EZ6"]},
        )
        assert empty.status_code == 422
        routine_id = created.json()["id"]

    now = datetime.now(UTC)
    async with engine.begin() as conn:
        await dispatch_due(conn, now=now)
        scan = await fetch_one(
            conn,
            """
            select id from jobs
            where routine_id = :routine_id and kind = 'ta_scan'
            """,
            {"routine_id": routine_id},
        )
    assert scan is not None
    deps = _deps(engine, generated_dir, tmp_path, worker_id="scan-worker")
    async with engine.begin() as conn:
        leased = await jobs.lease_job(
            conn, job_id=as_uuid(scan["id"]), worker_id="scan-worker", lease_seconds=180
        )
    assert leased is not None
    await TaScanJobHandler(deps).run(leased)
    events = await _count(
        engine,
        "select count(*) as n from ta_events",
        {},
    )
    decisions = await _count(
        engine,
        "select count(*) as n from trigger_decisions where routine_id = :id",
        {"id": routine_id},
    )
    enqueued = await _count(
        engine,
        """
        select count(*) as n from trigger_decisions
        where routine_id = :id and decision = 'enqueued'
        """,
        {"id": routine_id},
    )
    research_jobs = await _count(
        engine,
        """
        select count(*) as n from jobs
        where routine_id = :id and kind = 'research'
        """,
        {"id": routine_id},
    )
    assert events >= 1
    assert decisions == events
    assert enqueued == 1
    assert research_jobs == 1
    assert await _count(engine, "select count(*) as n from artifacts", {}) == artifacts_before

    async with engine.begin() as conn:
        sample = await fetch_one(
            conn,
            """
            select e.instrument_id, e.contract_code, e.timeframe, e.detector, e.calc_version,
                   e.data_revision, e.event_tz, e.direction, e.feature_id, d.confirmation_time
            from trigger_decisions d
            join ta_events e on e.id = d.event_id
            where d.routine_id = :id and d.decision = 'enqueued'
            """,
            {"id": routine_id},
        )
    assert sample is not None
    async with engine.begin() as conn:
        await fetch_one(
            conn,
            """
            insert into ta_events (
              feature_id, instrument_id, contract_code, timeframe, detector, calc_version,
              origin_time, data_revision, event_time, event_tz, direction, provenance
            ) values (
              :feature_id, :instrument_id, :contract_code, :timeframe, :detector, :calc_version,
              :origin_time, :data_revision, :event_time, :event_tz, :direction, 'fixture'
            )
            returning id
            """,
            {
                "feature_id": sample["feature_id"],
                "instrument_id": sample["instrument_id"],
                "contract_code": sample["contract_code"],
                "timeframe": sample["timeframe"],
                "detector": sample["detector"],
                "calc_version": sample["calc_version"],
                "origin_time": as_datetime(sample["confirmation_time"]) + timedelta(minutes=1),
                "data_revision": f"{as_str(sample['data_revision'])}-cooldown",
                "event_time": as_datetime(sample["confirmation_time"]) + timedelta(minutes=1),
                "event_tz": sample["event_tz"],
                "direction": sample["direction"],
            },
        )
        await evaluate_triggers(conn, now=now)
    cooled = await _count(
        engine,
        """
        select count(*) as n from trigger_decisions
        where routine_id = :id and decision = 'cooldown'
        """,
        {"id": routine_id},
    )
    assert cooled >= 1
    assert (
        await _count(
            engine,
            "select count(*) as n from jobs where routine_id = :id and kind = 'research'",
            {"id": routine_id},
        )
        == 1
    )

    async with engine.begin() as conn:
        await fetch_one(
            conn,
            "update routines set next_run_at = :now where id = :id returning id",
            {"now": now, "id": routine_id},
        )
        await dispatch_due(conn, now=now)
    assert (
        await _count(
            engine,
            "select count(*) as n from jobs where routine_id = :id and kind = 'ta_scan'",
            {"id": routine_id},
        )
        == 1
    )
    assert await _count(engine, "select count(*) as n from ta_events", {}) == events + 1


async def test_brief_tier_skips_web_retrieval(
    engine: AsyncEngine, generated_dir: Path, tmp_path: Path
) -> None:
    payload = ResearchPayload(
        symbol="6EZ6",
        question="Brief 6EZ6",
        owner_id=OWNER,
        tier="brief",
    )
    async with engine.begin() as conn:
        job = await jobs.enqueue_job(
            conn,
            kind="research",
            idempotency_key=f"brief-{uuid.uuid4()}",
            payload=cast("dict[str, JsonValue]", payload.model_dump(mode="json")),
            priority=5,
        )
        leased = await jobs.lease_job(
            conn, job_id=job.id, worker_id="brief-worker", lease_seconds=120
        )
    assert leased is not None
    deps = _deps(engine, generated_dir, tmp_path, worker_id="brief-worker")
    finished = await run_leased_job(deps, leased)
    assert finished.state == "completed"
    assert finished.checkpoint.get("retrievals_used") == 0
    warnings = finished.checkpoint.get("warnings")
    assert isinstance(warnings, list)
    assert "brief tier: web retrieval skipped" in warnings


async def test_budget_ceiling_is_configurable_and_market_data_is_separate(
    engine: AsyncEngine, automation_db: str, generated_dir: Path, tmp_path: Path
) -> None:
    start, end = analytics.month_bounds(datetime.now(UTC))
    async with engine.begin() as conn:
        ai_before = await analytics.month_spend(
            conn, start=start, end=end, categories="llm,search,fetch,source"
        )
        market_before = await analytics.month_spend(
            conn, start=start, end=end, categories="market_data"
        )
    with _client(automation_db, generated_dir) as http:
        updated = http.put("/v1/budgets/ai_search", json={"limit_usd": format(ai_before, "f")})
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["category"] == "ai_search"
        assert Decimal(body["limit_usd"]) == ai_before
        listed = http.get("/v1/budgets")
        assert listed.status_code == 200
        categories = {row["category"]: row for row in listed.json()}
        assert categories["market_data"]["enforced"] is False
        assert categories["ai_search"]["enforced"] is True

    limits = _limits(monthly_ai_search_usd="100000", monthly_market_data_usd="0")
    budget = BudgetService(engine, limits, run_id=None, job_id=None)
    with pytest.raises(BudgetExceededError):
        await budget.reserve(
            category="llm",
            provider="recorded",
            estimate=Decimal("0.01"),
            unit_type="calls",
        )
    reservation = await budget.reserve(
        category="market_data",
        provider="fixture",
        estimate=Decimal("50"),
        unit_type="records",
    )
    await budget.reconcile(reservation, Decimal("1"))
    async with engine.begin() as conn:
        ai_after = await analytics.month_spend(
            conn, start=start, end=end, categories="llm,search,fetch,source"
        )
        market_after = await analytics.month_spend(
            conn, start=start, end=end, categories="market_data"
        )
        await analytics.set_setting(
            conn,
            key="budget.market_data_monthly_usd",
            value={"usd": format(market_after, "f")},
            description="test ceiling",
        )
    assert ai_after == ai_before
    assert market_after == market_before + Decimal("1")
    tight = _limits(monthly_market_data_usd="0")
    blocked = BudgetService(engine, tight, run_id=None, job_id=None)
    with pytest.raises(BudgetExceededError):
        await blocked.reserve(
            category="market_data",
            provider="fixture",
            estimate=Decimal("0.01"),
            unit_type="records",
        )

    partial_limits = _limits(
        monthly_ai_search_usd=ai_before + Decimal("0.03"),
        llm_reserve_usd="0.02",
        retrieval_reserve_usd="0.01",
        max_evidence_tokens=1_000_000,
    )
    async with engine.begin() as conn:
        await analytics.set_setting(
            conn,
            key="budget.ai_search_monthly_usd",
            value={"usd": format(ai_before + Decimal("0.03"), "f")},
            description="partial ceiling",
        )
        job = await jobs.enqueue_job(
            conn,
            kind="research",
            idempotency_key=f"partial-budget-{uuid.uuid4()}",
            payload={
                "symbol": "6EZ6",
                "question": "Partial budget 6EZ6",
                "owner_id": str(LOCAL_DEV_USER_ID),
                "tier": "full",
            },
            priority=5,
        )
        leased = await jobs.lease_job(
            conn, job_id=job.id, worker_id="partial-budget", lease_seconds=120
        )
    assert leased is not None
    deps = _deps(
        engine,
        generated_dir,
        tmp_path,
        worker_id="partial-budget",
        limits=partial_limits,
    )
    deps.provider = _ScriptedProvider()
    finished = await run_leased_job(deps, leased)
    assert finished.state == "completed"
    assert finished.checkpoint.get("partial_research") is True
    assert finished.checkpoint.get("stop_reason") == "budget_ceiling"
    assert finished.checkpoint.get("thesis") is not None
    async with engine.begin() as conn:
        await analytics.set_setting(
            conn,
            key="budget.ai_search_monthly_usd",
            value={"usd": "100"},
            description="restore default ceiling",
        )


async def test_outcomes_api_reads_simulated_pnl_not_fills(
    engine: AsyncEngine, automation_db: str, generated_dir: Path, tmp_path: Path
) -> None:
    fills_before = await _count(engine, "select count(*) as n from imported_fills", {})
    async with engine.begin() as conn:
        await analytics.set_setting(
            conn,
            key="budget.ai_search_monthly_usd",
            value={"usd": "100"},
            description="test ceiling",
        )
    payload = {
        "symbol": "6EZ6",
        "question": "Outcome 6EZ6",
        "owner_id": str(OWNER),
        "tier": "brief",
    }
    deps = _deps(engine, generated_dir, tmp_path, worker_id="outcome-worker")
    async with engine.begin() as conn:
        job = await jobs.enqueue_job(
            conn,
            kind="research",
            idempotency_key=f"outcome-{uuid.uuid4()}",
            payload=cast("dict[str, JsonValue]", payload),
            priority=5,
        )
        leased = await jobs.lease_job(
            conn, job_id=job.id, worker_id="outcome-worker", lease_seconds=120
        )
    assert leased is not None
    finished = await run_leased_job(deps, leased)
    assert finished.state == "completed"
    adapter = FixtureAdapter(generated_dir)
    series = await adapter.get_bars(BarsRequest(symbol="6EZ6", timeframe="5m", limit=5000))
    complete = [bar for bar in series.bars if bar.is_complete]
    assert complete
    first = complete[0]
    last = complete[-1]
    frozen_at = first.origin_time - timedelta(minutes=1)
    entry = first.close
    async with engine.begin() as conn:
        row = await fetch_one(
            conn,
            """
            update hypotheses
            set frozen_at = :frozen_at,
                stance = 'bullish',
                entry = :entry,
                invalidation = 0,
                target = :target,
                entry_state = 'untriggered',
                status = 'open'
            where artifact_revision_id = :revision
            returning id
            """,
            {
                "frozen_at": frozen_at,
                "entry": entry,
                "target": entry + Decimal("1000"),
                "revision": finished.checkpoint["revision_id"],
            },
        )
        assert row is not None
        changed = await observe_open(conn, adapter)
    assert changed >= 1
    async with engine.begin() as conn:
        stored = await fetch_one(
            conn,
            """
            select entry_state, status, subsequent_move, simulated_pnl, pnl_label
            from hypotheses where id = :id
            """,
            {"id": row["id"]},
        )
    assert stored is not None
    assert stored["entry_state"] == "triggered"
    assert stored["status"] == "triggered"
    assert stored["pnl_label"] == "simulated"
    assert as_decimal(stored["subsequent_move"]) == last.close - entry
    assert as_decimal(stored["simulated_pnl"]) != 0 or last.close == entry
    assert await _count(engine, "select count(*) as n from imported_fills", {}) == fills_before

    with _client(automation_db, generated_dir) as http:
        listed = http.get("/v1/outcomes")
    assert listed.status_code == 200, listed.text
    match = next(item for item in listed.json() if item["id"] == str(row["id"]))
    assert match["pnl_label"] == "simulated"
    assert match["real_fills_included"] is False
    assert match["entry_state"] == "triggered"
    assert match["artifact_revision_id"] == str(finished.checkpoint["revision_id"])
    assert any(item["event"] == "entry_triggered" for item in match["observations"])
    assert as_str(match["symbol"])
