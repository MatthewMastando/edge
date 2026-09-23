"""Routines, in-app alerts, budgets and research outcomes.

The outcomes payload is what the Research Outcomes page reads. Simulated P&L is labeled
and is not mixed with imported fills.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncConnection

from trading_api.auth import UserDep
from trading_api.dependencies import DatabaseDep, FixtureAdapterDep, SettingsDep
from trading_api.settings import ApiSettings
from trading_core.automation.schedule import ScheduleError, next_occurrence, validate_timezone
from trading_core.data.adapter import UnknownSymbolError
from trading_core.domain.automation import (
    BudgetStatus,
    BudgetUpdate,
    HypothesisOutcome,
    Notification,
    Routine,
    RoutineCreate,
)
from trading_core.storage.repositories import analytics, automation, reference
from trading_core.storage.repositories.analytics import month_bounds

router = APIRouter(prefix="/v1", tags=["automation"])

BudgetCategory = Literal["ai_search", "market_data"]


@router.post("/routines", response_model=Routine, operation_id="createRoutine")
async def create_routine(
    body: RoutineCreate,
    user: UserDep,
    database: DatabaseDep,
    adapter: FixtureAdapterDep,
) -> Routine:
    _validate_schedule(body)
    now = datetime.now(UTC)
    instrument_ids: list[UUID] = []
    mapping: dict[str, str] = {}
    async with database.engine.begin() as conn:
        for symbol in body.symbols:
            try:
                resolved = await adapter.resolve(symbol)
            except UnknownSymbolError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown symbol {symbol}"
                ) from exc
            await reference.upsert_session_calendar(conn, resolved.calendar)
            instrument = await reference.upsert_instrument(conn, resolved.instrument)
            if resolved.contract is not None:
                await reference.upsert_futures_contract(
                    conn, resolved.contract.model_copy(update={"instrument_id": instrument.id})
                )
            if instrument.id not in instrument_ids:
                instrument_ids.append(instrument.id)
            mapping[str(instrument.id)] = symbol
        nxt = _next_run(body, now)
        return await automation.insert_routine(
            conn,
            owner_id=user.id,
            name=body.name,
            kind=body.kind,
            schedule_cron=body.schedule_cron,
            schedule_timezone=body.schedule_timezone,
            instrument_ids=instrument_ids,
            symbols=list(body.symbols),
            tier=body.tier,
            event_allowlist=list(body.event_allowlist),
            cooldown_seconds=body.cooldown_seconds,
            daily_cap=body.daily_cap,
            crypto_monitoring=body.crypto_monitoring,
            question=body.question,
            timeframe=body.timeframe,
            symbol_by_instrument=mapping,
            next_run_at=nxt,
        )


@router.get("/routines", response_model=list[Routine], operation_id="listRoutines")
async def list_routines(user: UserDep, database: DatabaseDep) -> list[Routine]:
    async with database.engine.begin() as conn:
        return await automation.list_routines(conn, user.id)


@router.get("/notifications", response_model=list[Notification], operation_id="listNotifications")
async def list_notifications(
    user: UserDep,
    database: DatabaseDep,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[Notification]:
    async with database.engine.begin() as conn:
        return await automation.list_notifications(conn, user.id, limit)


@router.get("/outcomes", response_model=list[HypothesisOutcome], operation_id="listOutcomes")
async def list_outcomes(user: UserDep, database: DatabaseDep) -> list[HypothesisOutcome]:
    """Frozen hypotheses for Research Outcomes. Simulated P&L is never a real fill."""
    async with database.engine.begin() as conn:
        return await automation.list_outcomes(conn, user.id)


@router.get("/budgets", response_model=list[BudgetStatus], operation_id="listBudgets")
async def list_budgets(
    user: UserDep, database: DatabaseDep, settings: SettingsDep
) -> list[BudgetStatus]:
    del user
    now = datetime.now(UTC)
    start, end = month_bounds(now)
    async with database.engine.begin() as conn:
        return [
            await _status(conn, "ai_search", start, end, settings.monthly_ai_search_usd),
            await _status(conn, "market_data", start, end, settings.monthly_market_data_usd),
        ]


@router.put("/budgets/{category}", response_model=BudgetStatus, operation_id="updateBudget")
async def update_budget(
    category: BudgetCategory,
    body: BudgetUpdate,
    user: UserDep,
    database: DatabaseDep,
    settings: SettingsDep,
) -> BudgetStatus:
    del user
    now = datetime.now(UTC)
    start, end = month_bounds(now)
    key = f"budget.{category}_monthly_usd"
    async with database.engine.begin() as conn:
        await analytics.set_setting(
            conn,
            key=key,
            value={"usd": format(body.limit_usd, "f")},
            description=f"Monthly {category} ceiling in USD",
        )
        await analytics.upsert_budget(
            conn, category=category, period_start=start, limit_usd=body.limit_usd
        )
        return await _status(conn, category, start, end, _settings_fallback(settings, category))


def _validate_schedule(body: RoutineCreate) -> None:
    try:
        validate_timezone(body.schedule_timezone)
    except ScheduleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if body.kind == "scheduled_briefing" and not body.schedule_cron:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="scheduled briefings require a cron expression",
        )
    if body.schedule_cron:
        try:
            next_occurrence(body.schedule_cron, body.schedule_timezone, after=datetime.now(UTC))
        except ScheduleError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc
    if body.kind == "ta_trigger" and not body.event_allowlist:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="TA triggers require an event allowlist",
        )


def _next_run(body: RoutineCreate, now: datetime) -> datetime:
    if body.kind == "scheduled_briefing" and body.schedule_cron:
        return next_occurrence(body.schedule_cron, body.schedule_timezone, after=now)
    return now


async def _status(
    conn: AsyncConnection,
    category: BudgetCategory,
    start: datetime,
    end: datetime,
    fallback: Decimal,
) -> BudgetStatus:
    key = f"budget.{category}_monthly_usd"
    stored = await analytics.get_setting(conn, key)
    limit = fallback
    raw = stored.get("usd") if stored is not None else None
    if isinstance(raw, str):
        limit = Decimal(raw)
    categories = "market_data" if category == "market_data" else "llm,search,fetch,source"
    spent = await analytics.month_spend(conn, start=start, end=end, categories=categories)
    enforced = not (category == "market_data" and limit == 0)
    return BudgetStatus(
        category=category,
        period_start=start.date(),
        limit_usd=limit,
        spent_usd=spent,
        enforced=enforced,
    )


def _settings_fallback(settings: ApiSettings, category: BudgetCategory) -> Decimal:
    if category == "ai_search":
        return settings.monthly_ai_search_usd
    return settings.monthly_market_data_usd
