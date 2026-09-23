"""Enqueue due routines and decide which confirmed TA events become research jobs.

Job idempotency keys include the routine, instrument and slot or confirmation time, so a
worker restart cannot create a second job or a second artifact for the same occurrence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast
from uuid import UUID

from pydantic import ValidationError

from trading_core.automation.rules import market_is_open, trigger_decision
from trading_core.automation.schedule import ScheduleError, local_midnight, next_occurrence
from trading_core.domain.instruments import SessionCalendar
from trading_core.harness.deps import ResearchPayload
from trading_core.storage.repositories import automation as store
from trading_core.storage.repositories import jobs
from trading_core.storage.repositories.common import as_datetime, as_json_dict, as_str, as_uuid

if TYPE_CHECKING:
    from pydantic import JsonValue
    from sqlalchemy.ext.asyncio import AsyncConnection

    from trading_core.domain.automation import Routine
    from trading_core.domain.jobs import Job, JobKind

_SCAN_GAP = timedelta(minutes=15)
_EVENT_PAGE = 200


async def dispatch_due(conn: AsyncConnection, *, now: datetime) -> int:
    """Schedule due briefings and scans, then apply trigger rules. Returns jobs enqueued."""
    created = 0
    for routine in await store.lock_due_routines(conn, now):
        slot = routine.next_run_at or now
        if routine.kind == "scheduled_briefing" and routine.schedule_cron:
            created += await _enqueue_briefings(conn, routine, slot)
        elif routine.kind == "ta_trigger":
            created += await _enqueue_scan(conn, routine, now)
        await store.advance_routine(
            conn,
            routine_id=routine.id,
            next_run_at=_following(routine, now, slot),
            ran_at=now,
        )
    created += await evaluate_triggers(conn, now=now)
    if await _enqueue_hypothesis_check(conn, now):
        created += 1
    return created


async def evaluate_triggers(conn: AsyncConnection, *, now: datetime) -> int:
    """Record a decision for every new confirmed event. Enqueue only when rules pass."""
    created = 0
    for routine in await store.list_trigger_routines(conn):
        created += await _evaluate_routine(conn, routine, now)
    return created


async def _evaluate_routine(conn: AsyncConnection, routine: Routine, now: datetime) -> int:
    start = local_midnight(now, routine.schedule_timezone)
    enqueued_today = await store.count_enqueued_since(conn, routine_id=routine.id, start=start)
    allowlist = set(routine.event_allowlist)
    created = 0
    while True:
        events = await store.events_without_decision(
            conn, routine_id=routine.id, instrument_ids=routine.instrument_ids
        )
        if not events:
            break
        created += await _decide_events(conn, routine, events, allowlist, enqueued_today, now)
        enqueued_today = await store.count_enqueued_since(conn, routine_id=routine.id, start=start)
        if len(events) < _EVENT_PAGE:
            break
    return created


async def _decide_events(
    conn: AsyncConnection,
    routine: Routine,
    events: list[dict[str, object]],
    allowlist: set[str],
    enqueued_today: int,
    now: datetime,
) -> int:
    created = 0
    for event in events:
        confirmation = as_datetime(event["event_time"])
        instrument_id = as_uuid(event["instrument_id"])
        detector = as_str(event["detector"])
        last = await store.latest_enqueued_confirmation(
            conn, routine_id=routine.id, instrument_id=instrument_id, detector=detector
        )
        decision = trigger_decision(
            detector=detector,
            allowlist=allowlist,
            confirmation_time=confirmation,
            last_enqueued_at=last,
            cooldown_seconds=routine.cooldown_seconds,
            enqueued_today=enqueued_today,
            daily_cap=routine.daily_cap,
            market_open=await _event_market_open(conn, routine, instrument_id, confirmation),
        )
        job_id = None
        if decision == "enqueued":
            symbol = _event_symbol(routine, event.get("contract_code"))
            if symbol is None or routine.owner_id is None:
                decision = "allowlist"
            else:
                job = await _research_job(
                    conn,
                    routine=routine,
                    symbol=symbol,
                    idempotency_key=_trigger_key(routine.id, instrument_id, detector, confirmation),
                    scheduled_for=confirmation if confirmation <= now else now,
                )
                job_id = job.id
                enqueued_today += 1
                created += 1
        await store.insert_trigger_decision(
            conn,
            routine_id=routine.id,
            event_id=as_uuid(event["id"]),
            instrument_id=instrument_id,
            detector=detector,
            confirmation_time=confirmation,
            decision=decision,
            job_id=job_id,
        )
    return created


async def _enqueue_briefings(conn: AsyncConnection, routine: Routine, slot: datetime) -> int:
    if routine.owner_id is None:
        return 0
    created = 0
    for symbol in routine.symbols:
        if not await _symbol_open(conn, routine, symbol, slot):
            continue
        await _research_job(
            conn,
            routine=routine,
            symbol=symbol,
            idempotency_key=f"schedule:{routine.id}:{symbol}:{_slot(slot)}",
            scheduled_for=slot,
            kind="scheduled_briefing",
        )
        created += 1
    return created


async def _enqueue_scan(conn: AsyncConnection, routine: Routine, now: datetime) -> int:
    """Record every symbol. Market hours gate the research job, not the TA log."""
    symbols = list(routine.symbols)
    if not symbols:
        return 0
    payload = cast(
        "dict[str, JsonValue]",
        {
            "routine_id": str(routine.id),
            "symbols": symbols,
            "timeframe": routine.timeframe,
        },
    )
    await jobs.enqueue_job(
        conn,
        kind="ta_scan",
        idempotency_key=f"ta-scan:{routine.id}:{now.strftime('%Y-%m-%dT%H')}",
        payload=payload,
        routine_id=routine.id,
        scheduled_tz=routine.schedule_timezone,
        priority=1,
    )
    return 1


async def _enqueue_hypothesis_check(conn: AsyncConnection, now: datetime) -> bool:
    key = f"hypothesis-check:{now.strftime('%Y-%m-%dT%H')}"
    if await jobs.get_job_by_key(conn, key) is not None:
        return False
    if await store.count_open_hypotheses(conn) == 0:
        return False
    await jobs.enqueue_job(
        conn,
        kind="hypothesis_check",
        idempotency_key=key,
        payload={},
        priority=0,
    )
    return True


async def _research_job(
    conn: AsyncConnection,
    *,
    routine: Routine,
    symbol: str,
    idempotency_key: str,
    scheduled_for: datetime,
    kind: JobKind = "research",
) -> Job:
    question = routine.question or f"What changed for {symbol}?"
    # TA triggers stay on the brief tier so a confirmed event cannot start web retrieval.
    tier = "brief" if routine.kind == "ta_trigger" else routine.tier
    payload = cast(
        "dict[str, JsonValue]",
        ResearchPayload(
            symbol=symbol,
            question=question,
            timeframe=routine.timeframe,
            owner_id=routine.owner_id,
            tier=tier,
        ).model_dump(mode="json"),
    )
    return await jobs.enqueue_job(
        conn,
        kind=kind,
        idempotency_key=idempotency_key,
        payload=payload,
        routine_id=routine.id,
        scheduled_for=scheduled_for,
        scheduled_tz=routine.schedule_timezone,
        priority=5,
    )


async def _symbol_open(
    conn: AsyncConnection, routine: Routine, symbol: str, when: datetime
) -> bool:
    instrument_id = _instrument_for_symbol(routine, symbol)
    if instrument_id is None:
        return False
    return await _event_market_open(conn, routine, instrument_id, when)


async def _event_market_open(
    conn: AsyncConnection, routine: Routine, instrument_id: UUID, when: datetime
) -> bool:
    row = await store.instrument_context(conn, instrument_id)
    if row is None or row.get("definition") is None:
        return False
    try:
        calendar = SessionCalendar.model_validate(as_json_dict(row["definition"]))
    except (TypeError, ValidationError):
        return False
    return market_is_open(
        calendar,
        when,
        asset_class=as_str(row["asset_class"]),
        crypto_monitoring=routine.crypto_monitoring,
    )


def _instrument_for_symbol(routine: Routine, symbol: str) -> UUID | None:
    for raw_id, mapped in routine.symbol_by_instrument.items():
        if mapped == symbol:
            return UUID(raw_id)
    if len(routine.instrument_ids) == 1:
        return routine.instrument_ids[0]
    return None


def _event_symbol(routine: Routine, contract_code: object) -> str | None:
    if isinstance(contract_code, str) and contract_code in routine.symbols:
        return contract_code
    if len(routine.symbols) == 1:
        return routine.symbols[0]
    return None


def _trigger_key(
    routine_id: UUID, instrument_id: UUID, detector: str, confirmation: datetime
) -> str:
    return f"trigger:{routine_id}:{instrument_id}:{detector}:{_slot(confirmation)}"


def _slot(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _following(routine: Routine, now: datetime, slot: datetime) -> datetime:
    if routine.schedule_cron:
        try:
            return next_occurrence(
                routine.schedule_cron, routine.schedule_timezone, after=max(now, slot)
            )
        except ScheduleError:
            return now + timedelta(days=1)
    return now + _SCAN_GAP
