# ruff: noqa: S608
"""Routines, trigger decisions, outcomes and alert reads."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from trading_core.domain.automation import (
    AlertKind,
    CryptoMonitoring,
    EntryState,
    HypothesisObservationView,
    HypothesisOutcome,
    HypothesisStatus,
    Notification,
    ResearchTier,
    Routine,
    RoutineKind,
)
from trading_core.storage.db import fetch_all, fetch_one
from trading_core.storage.repositories.common import (
    as_datetime,
    as_datetime_or_none,
    as_decimal,
    as_int,
    as_json_dict,
    as_str,
    as_str_or_none,
    as_uuid,
    as_uuid_or_none,
    json_param,
    uuid_array,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from pydantic import JsonValue
    from sqlalchemy.ext.asyncio import AsyncConnection

    from trading_core.domain.common import Timeframe

_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1d"}
_ROUTINE_KINDS = {"scheduled_briefing", "ta_trigger", "manual"}
_TIERS = {"full", "brief"}
_CRYPTO = {"always", "calendar"}


NotificationSeverity = Literal["info", "warning", "error"]
StanceName = Literal["bullish", "bearish", "neutral", "insufficient_evidence"]
ObservationEventName = Literal[
    "checkpoint", "entry_triggered", "invalidation_hit", "target_hit", "expired"
]


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items() if isinstance(item, str)}


def _optional_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _uuid_list(value: object) -> list[UUID]:
    if not isinstance(value, list):
        return []
    found: list[UUID] = []
    for item in value:
        if isinstance(item, UUID):
            found.append(item)
        elif isinstance(item, str):
            found.append(UUID(item))
    return found


def _tier(value: object) -> ResearchTier:
    if isinstance(value, str) and value in _TIERS:
        return cast("ResearchTier", value)
    return "brief"


def _timeframe(value: object) -> Timeframe:
    if isinstance(value, str) and value in _TIMEFRAMES:
        return cast("Timeframe", value)
    return "5m"


def _crypto(value: object) -> CryptoMonitoring:
    if isinstance(value, str) and value in _CRYPTO:
        return cast("CryptoMonitoring", value)
    return "always"


def routine_from_row(row: dict[str, object]) -> Routine:
    config = as_json_dict(row["config"])
    kind = as_str(row["kind"])
    if kind not in _ROUTINE_KINDS:
        kind = "manual"
    return Routine(
        id=as_uuid(row["id"]),
        owner_id=as_uuid_or_none(row["owner_id"]),
        name=as_str(row["name"]),
        kind=cast("RoutineKind", kind),
        enabled=bool(row["enabled"]),
        schedule_cron=as_str_or_none(row["schedule_cron"]),
        schedule_timezone=as_str(row["schedule_timezone"], "America/New_York"),
        instrument_ids=_uuid_list(row["instrument_ids"]),
        symbols=_text_list(config.get("symbols")),
        symbol_by_instrument=_string_map(config.get("symbol_by_instrument")),
        tier=_tier(config.get("tier")),
        event_allowlist=_text_list(config.get("event_allowlist")),
        cooldown_seconds=as_int(row["cooldown_seconds"], 14_400),
        daily_cap=as_int(row["daily_cap"], 6),
        crypto_monitoring=_crypto(config.get("crypto_monitoring")),
        question=_optional_text(config.get("question")),
        timeframe=_timeframe(config.get("timeframe")),
        last_run_at=as_datetime_or_none(row["last_run_at"]),
        next_run_at=as_datetime_or_none(row["next_run_at"]),
        created_at=as_datetime(row["created_at"]),
        updated_at=as_datetime(row["updated_at"]),
    )


def _config(
    *,
    symbols: list[str],
    tier: str,
    event_allowlist: list[str],
    crypto_monitoring: str,
    question: str | None,
    timeframe: str,
    symbol_by_instrument: dict[str, str],
) -> dict[str, JsonValue]:
    payload = cast(
        "dict[str, JsonValue]",
        {
            "symbols": symbols,
            "tier": tier,
            "event_allowlist": event_allowlist,
            "crypto_monitoring": crypto_monitoring,
            "timeframe": timeframe,
            "symbol_by_instrument": symbol_by_instrument,
        },
    )
    if question is not None:
        payload["question"] = question
    return payload


async def insert_routine(
    conn: AsyncConnection,
    *,
    owner_id: UUID,
    name: str,
    kind: str,
    schedule_cron: str | None,
    schedule_timezone: str,
    instrument_ids: list[UUID],
    symbols: list[str],
    tier: str,
    event_allowlist: list[str],
    cooldown_seconds: int,
    daily_cap: int,
    crypto_monitoring: str,
    question: str | None,
    timeframe: str,
    symbol_by_instrument: dict[str, str],
    next_run_at: datetime | None,
) -> Routine:
    row = await fetch_one(
        conn,
        """
        insert into routines (
          owner_id, name, kind, schedule_cron, schedule_timezone, instrument_ids, config,
          cooldown_seconds, daily_cap, next_run_at
        ) values (
          :owner_id, :name, :kind, :schedule_cron, :schedule_timezone,
          case when :instrument_ids = '' then '{}'::uuid[]
               else cast(string_to_array(:instrument_ids, ',') as uuid[]) end,
          cast(:config as jsonb), :cooldown_seconds, :daily_cap, :next_run_at
        )
        returning id, owner_id, name, kind, enabled, schedule_cron, schedule_timezone,
          instrument_ids, config, cooldown_seconds, daily_cap, last_run_at, next_run_at,
          created_at, updated_at
        """,
        {
            "owner_id": owner_id,
            "name": name,
            "kind": kind,
            "schedule_cron": schedule_cron,
            "schedule_timezone": schedule_timezone,
            "instrument_ids": uuid_array(instrument_ids),
            "config": json_param(
                _config(
                    symbols=symbols,
                    tier=tier,
                    event_allowlist=event_allowlist,
                    crypto_monitoring=crypto_monitoring,
                    question=question,
                    timeframe=timeframe,
                    symbol_by_instrument=symbol_by_instrument,
                )
            ),
            "cooldown_seconds": cooldown_seconds,
            "daily_cap": daily_cap,
            "next_run_at": next_run_at,
        },
    )
    if row is None:
        msg = "routine insert returned no row"
        raise RuntimeError(msg)
    return routine_from_row(row)


_ROUTINE_COLUMNS = """
id, owner_id, name, kind, enabled, schedule_cron, schedule_timezone, instrument_ids, config,
cooldown_seconds, daily_cap, last_run_at, next_run_at, created_at, updated_at
"""


async def list_routines(conn: AsyncConnection, owner_id: UUID) -> list[Routine]:
    rows = await fetch_all(
        conn,
        f"""
        select {_ROUTINE_COLUMNS}
        from routines
        where owner_id = :owner_id
        order by created_at desc
        limit 100
        """,
        {"owner_id": owner_id},
    )
    return [routine_from_row(row) for row in rows]


async def lock_due_routines(conn: AsyncConnection, now: datetime) -> list[Routine]:
    rows = await fetch_all(
        conn,
        f"""
        select {_ROUTINE_COLUMNS}
        from routines
        where enabled
          and kind in ('scheduled_briefing', 'ta_trigger')
          and next_run_at is not null
          and next_run_at <= :now
        order by next_run_at, id
        limit 20
        for update skip locked
        """,
        {"now": now},
    )
    return [routine_from_row(row) for row in rows]


async def list_trigger_routines(conn: AsyncConnection) -> list[Routine]:
    rows = await fetch_all(
        conn,
        f"""
        select {_ROUTINE_COLUMNS}
        from routines
        where enabled and kind = 'ta_trigger'
        order by created_at
        limit 50
        """,
    )
    return [routine_from_row(row) for row in rows]


async def advance_routine(
    conn: AsyncConnection, *, routine_id: UUID, next_run_at: datetime, ran_at: datetime
) -> None:
    await fetch_one(
        conn,
        """
        update routines
        set next_run_at = :next_run_at, last_run_at = :ran_at
        where id = :id
        returning id
        """,
        {"id": routine_id, "next_run_at": next_run_at, "ran_at": ran_at},
    )


async def events_without_decision(
    conn: AsyncConnection, *, routine_id: UUID, instrument_ids: list[UUID]
) -> list[dict[str, object]]:
    if not instrument_ids:
        return []
    return await fetch_all(
        conn,
        """
        select e.id, e.instrument_id, e.contract_code, e.detector, e.event_time, e.event_tz
        from ta_events e
        where e.instrument_id = any(cast(string_to_array(:ids, ',') as uuid[]))
          and not exists (
            select 1 from trigger_decisions d
            where d.routine_id = :routine_id and d.event_id = e.id
          )
        order by e.event_time, e.id
        limit 200
        """,
        {"ids": uuid_array(instrument_ids), "routine_id": routine_id},
    )


async def latest_enqueued_confirmation(
    conn: AsyncConnection, *, routine_id: UUID, instrument_id: UUID, detector: str
) -> datetime | None:
    row = await fetch_one(
        conn,
        """
        select max(confirmation_time) as confirmation_time
        from trigger_decisions
        where routine_id = :routine_id
          and instrument_id = :instrument_id
          and detector = :detector
          and decision = 'enqueued'
        """,
        {"routine_id": routine_id, "instrument_id": instrument_id, "detector": detector},
    )
    if row is None:
        return None
    return as_datetime_or_none(row["confirmation_time"])


async def count_enqueued_since(conn: AsyncConnection, *, routine_id: UUID, start: datetime) -> int:
    row = await fetch_one(
        conn,
        """
        select count(*) as n
        from trigger_decisions
        where routine_id = :routine_id and decision = 'enqueued' and created_at >= :start
        """,
        {"routine_id": routine_id, "start": start},
    )
    if row is None:
        return 0
    return as_int(row["n"])


async def insert_trigger_decision(
    conn: AsyncConnection,
    *,
    routine_id: UUID,
    event_id: UUID,
    instrument_id: UUID,
    detector: str,
    confirmation_time: datetime,
    decision: str,
    job_id: UUID | None,
) -> None:
    await fetch_one(
        conn,
        """
        insert into trigger_decisions (
          routine_id, event_id, instrument_id, detector, confirmation_time, decision, job_id
        ) values (
          :routine_id, :event_id, :instrument_id, :detector, :confirmation_time, :decision, :job_id
        )
        on conflict (routine_id, event_id) do nothing
        returning id
        """,
        {
            "routine_id": routine_id,
            "event_id": event_id,
            "instrument_id": instrument_id,
            "detector": detector,
            "confirmation_time": confirmation_time,
            "decision": decision,
            "job_id": job_id,
        },
    )


async def count_open_hypotheses(conn: AsyncConnection) -> int:
    row = await fetch_one(
        conn,
        """
        select count(*) as n from hypotheses
        where status in ('open', 'triggered')
        """,
    )
    if row is None:
        return 0
    return as_int(row["n"])


async def list_notifications(
    conn: AsyncConnection, owner_id: UUID, limit: int
) -> list[Notification]:
    rows = await fetch_all(
        conn,
        """
        select id, kind, severity, title, body, run_id, artifact_id, read_at, created_at
        from notifications
        where owner_id = :owner_id
        order by created_at desc
        limit :limit
        """,
        {"owner_id": owner_id, "limit": limit},
    )
    notes: list[Notification] = []
    for row in rows:
        kind = as_str(row["kind"])
        notes.append(
            Notification(
                id=as_uuid(row["id"]),
                kind=cast("AlertKind", kind),
                severity=cast("NotificationSeverity", as_str(row["severity"])),
                title=as_str(row["title"]),
                body=as_str_or_none(row["body"]),
                run_id=as_uuid_or_none(row["run_id"]),
                artifact_id=as_uuid_or_none(row["artifact_id"]),
                read_at=as_datetime_or_none(row["read_at"]),
                created_at=as_datetime(row["created_at"]),
            )
        )
    return notes


def _outcome(row: dict[str, object]) -> HypothesisOutcome:
    status = as_str(row["status"])
    entry_state = as_str(row["entry_state"])
    stance = as_str(row["stance"])
    return HypothesisOutcome(
        id=as_uuid(row["id"]),
        artifact_revision_id=as_uuid(row["artifact_revision_id"]),
        instrument_id=as_uuid(row["instrument_id"]),
        symbol=as_str(row["symbol"]),
        contract_code=as_str_or_none(row["contract_code"]),
        stance=cast("StanceName", stance),
        entry=_decimal_or_none(row["entry"]),
        invalidation=_decimal_or_none(row["invalidation"]),
        target=_decimal_or_none(row["target"]),
        horizon=as_str(row["horizon"]),
        frozen_at=as_datetime(row["frozen_at"]),
        status=cast("HypothesisStatus", status),
        entry_state=cast("EntryState", entry_state),
        subsequent_move=_decimal_or_none(row["subsequent_move"]),
        simulated_pnl=_decimal_or_none(row["simulated_pnl"]),
        simulated_pnl_currency=as_str_or_none(row["simulated_pnl_currency"]),
        assumptions=as_json_dict(row["assumptions"]),
        observations=[],
    )


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return as_decimal(value)


async def list_outcomes(conn: AsyncConnection, owner_id: UUID) -> list[HypothesisOutcome]:
    rows = await fetch_all(
        conn,
        """
        select h.id, h.artifact_revision_id, h.instrument_id, i.symbol, h.contract_code,
          h.stance, h.entry, h.invalidation, h.target, h.horizon, h.frozen_at, h.status,
          h.entry_state, h.subsequent_move, h.simulated_pnl, h.simulated_pnl_currency,
          h.assumptions
        from hypotheses h
        join instruments i on i.id = h.instrument_id
        join artifact_revisions r on r.id = h.artifact_revision_id
        join artifacts a on a.id = r.artifact_id
        where a.owner_id = :owner_id
        order by h.frozen_at desc
        limit 100
        """,
        {"owner_id": owner_id},
    )
    outcomes = [_outcome(row) for row in rows]
    if not outcomes:
        return []
    observations = await fetch_all(
        conn,
        """
        select id, hypothesis_id, observed_at, observed_tz, price, event, data_revision, note
        from hypothesis_observations
        where hypothesis_id = any(cast(string_to_array(:ids, ',') as uuid[]))
        order by observed_at, id
        """,
        {"ids": uuid_array([item.id for item in outcomes])},
    )
    grouped: dict[UUID, list[HypothesisObservationView]] = {}
    for row in observations:
        hypothesis_id = as_uuid(row["hypothesis_id"])
        grouped.setdefault(hypothesis_id, []).append(
            HypothesisObservationView(
                id=as_uuid(row["id"]),
                observed_at=as_datetime(row["observed_at"]),
                observed_tz=as_str(row["observed_tz"], "UTC"),
                price=as_decimal(row["price"]),
                event=cast("ObservationEventName", as_str(row["event"])),
                data_revision=as_str(row["data_revision"]),
                note=as_str_or_none(row["note"]),
            )
        )
    return [item.model_copy(update={"observations": grouped.get(item.id, [])}) for item in outcomes]


async def list_hypotheses_to_check(conn: AsyncConnection) -> list[dict[str, object]]:
    return await fetch_all(
        conn,
        """
        select h.id, h.artifact_revision_id, h.instrument_id, h.contract_code, h.stance,
          h.entry, h.invalidation, h.target, h.frozen_at, h.status, h.entry_state,
          h.assumptions, i.symbol, i.multiplier, i.currency, i.asset_class
        from hypotheses h
        join instruments i on i.id = h.instrument_id
        where h.status in ('open', 'triggered')
        order by h.frozen_at
        limit 100
        """,
    )


async def update_hypothesis_outcome(
    conn: AsyncConnection,
    *,
    hypothesis_id: UUID,
    status: str,
    entry_state: str,
    subsequent_move: Decimal | None,
    simulated_pnl: Decimal | None,
    simulated_pnl_currency: str | None,
    assumptions: dict[str, JsonValue],
) -> None:
    await fetch_one(
        conn,
        """
        update hypotheses
        set status = :status,
            entry_state = :entry_state,
            subsequent_move = :subsequent_move,
            simulated_pnl = :simulated_pnl,
            simulated_pnl_currency = :simulated_pnl_currency,
            pnl_label = 'simulated',
            assumptions = cast(:assumptions as jsonb)
        where id = :id
        returning id
        """,
        {
            "id": hypothesis_id,
            "status": status,
            "entry_state": entry_state,
            "subsequent_move": subsequent_move,
            "simulated_pnl": simulated_pnl,
            "simulated_pnl_currency": simulated_pnl_currency,
            "assumptions": json_param(assumptions),
        },
    )


async def insert_observation_once(
    conn: AsyncConnection,
    *,
    hypothesis_id: UUID,
    observed_at: datetime,
    observed_tz: str,
    price: Decimal,
    event: str,
    data_revision: str,
    note: str | None,
) -> None:
    await fetch_one(
        conn,
        """
        insert into hypothesis_observations (
          hypothesis_id, observed_at, observed_tz, price, event, data_revision, note
        ) values (
          :hypothesis_id, :observed_at, :observed_tz, :price, :event, :data_revision, :note
        )
        on conflict (hypothesis_id, event, data_revision) do nothing
        returning id
        """,
        {
            "hypothesis_id": hypothesis_id,
            "observed_at": observed_at,
            "observed_tz": observed_tz,
            "price": price,
            "event": event,
            "data_revision": data_revision,
            "note": note,
        },
    )


async def freeze_hypothesis(
    conn: AsyncConnection,
    *,
    artifact_revision_id: UUID,
    instrument_id: UUID,
    contract_code: str | None,
    stance: str,
    entry: Decimal | None,
    invalidation: Decimal | None,
    target: Decimal | None,
    horizon: str,
    expires_at: datetime | None,
    assumptions: dict[str, JsonValue],
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into hypotheses (
          artifact_revision_id, instrument_id, contract_code, stance, entry, invalidation,
          target, horizon, expires_at, status, entry_state, assumptions, pnl_label
        ) values (
          :artifact_revision_id, :instrument_id, :contract_code, :stance, :entry, :invalidation,
          :target, :horizon, :expires_at, 'open', 'untriggered', cast(:assumptions as jsonb),
          'simulated'
        )
        on conflict (artifact_revision_id) do nothing
        returning id
        """,
        {
            "artifact_revision_id": artifact_revision_id,
            "instrument_id": instrument_id,
            "contract_code": contract_code,
            "stance": stance,
            "entry": entry,
            "invalidation": invalidation,
            "target": target,
            "horizon": horizon,
            "expires_at": expires_at,
            "assumptions": json_param(assumptions),
        },
    )
    if row is not None:
        return as_uuid(row["id"])
    existing = await fetch_one(
        conn,
        "select id from hypotheses where artifact_revision_id = :id",
        {"id": artifact_revision_id},
    )
    if existing is None:
        msg = "hypothesis freeze conflicted without a row"
        raise RuntimeError(msg)
    return as_uuid(existing["id"])


async def previous_structured(
    conn: AsyncConnection, *, instrument_id: UUID, revision_id: UUID
) -> dict[str, JsonValue] | None:
    row = await fetch_one(
        conn,
        """
        select ar.structured
        from artifact_revisions ar
        join artifacts a on a.id = ar.artifact_id
        where a.instrument_id = :instrument_id and ar.id <> :revision_id
        order by ar.revision_number desc
        limit 1
        """,
        {"instrument_id": instrument_id, "revision_id": revision_id},
    )
    if row is None:
        return None
    return as_json_dict(row["structured"])


async def instrument_context(
    conn: AsyncConnection, instrument_id: UUID
) -> dict[str, object] | None:
    return await fetch_one(
        conn,
        """
        select i.id, i.symbol, i.asset_class, i.session_calendar_id, c.definition
        from instruments i
        left join lateral (
          select definition from session_calendars
          where id = i.session_calendar_id
          order by created_at desc
          limit 1
        ) c on true
        where i.id = :id
        """,
        {"id": instrument_id},
    )
