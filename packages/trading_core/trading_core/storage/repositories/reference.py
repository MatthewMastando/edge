# ruff: noqa: S608
"""Instruments, futures contracts, rolls, session calendars and watchlists."""

from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING, cast

from trading_core.domain.instruments import (
    FuturesContract,
    Instrument,
    RollMapEntry,
    SessionCalendar,
)
from trading_core.storage.db import fetch_all, fetch_one
from trading_core.storage.repositories.common import (
    as_bool,
    as_decimal,
    as_str,
    as_str_or_none,
    as_uuid,
    json_param,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection

    from trading_core.domain.common import Provenance

_INSTRUMENT_RETURNING = """
returning id, symbol, name, asset_class, venue, currency, tick_size, tick_value, multiplier,
          session_calendar_id, base_asset, quote_asset, is_continuous, provenance
"""


def _instrument(row: dict[str, object]) -> Instrument:
    return Instrument.model_validate(
        {
            "id": as_uuid(row["id"]),
            "symbol": as_str(row["symbol"]),
            "name": as_str(row["name"]),
            "asset_class": as_str(row["asset_class"]),
            "venue": as_str(row["venue"]),
            "currency": as_str(row["currency"]),
            "tick_size": as_decimal(row["tick_size"]),
            "tick_value": as_decimal(row["tick_value"]),
            "multiplier": as_decimal(row["multiplier"]),
            "session_calendar_id": as_str(row["session_calendar_id"]),
            "base_asset": as_str_or_none(row["base_asset"]),
            "quote_asset": as_str_or_none(row["quote_asset"]),
            "is_continuous": as_bool(row["is_continuous"]),
            "provenance": as_str(row["provenance"]),
        }
    )


async def upsert_session_calendar(conn: AsyncConnection, calendar: SessionCalendar) -> None:
    await fetch_one(
        conn,
        """
        insert into session_calendars (
          id, version, name, timezone, exchange_calendar_code, always_open, definition, notes
        ) values (
          :id, :version, :name, :timezone, :exchange_calendar_code, :always_open,
          cast(:definition as jsonb), :notes
        )
        on conflict (id, version) do update set
          name = excluded.name,
          timezone = excluded.timezone,
          exchange_calendar_code = excluded.exchange_calendar_code,
          always_open = excluded.always_open,
          definition = excluded.definition,
          notes = excluded.notes
        returning id
        """,
        {
            "id": calendar.id,
            "version": calendar.version,
            "name": calendar.name,
            "timezone": calendar.timezone,
            "exchange_calendar_code": calendar.exchange_calendar_code,
            "always_open": calendar.always_open,
            "definition": json_param(calendar.model_dump(mode="json")),
            "notes": calendar.notes,
        },
    )


async def upsert_instrument(conn: AsyncConnection, instrument: Instrument) -> Instrument:
    row = await fetch_one(
        conn,
        f"""
        insert into instruments (
          id, symbol, name, asset_class, venue, currency, tick_size, tick_value, multiplier,
          session_calendar_id, base_asset, quote_asset, is_continuous, provenance
        ) values (
          :id, :symbol, :name, :asset_class, :venue, :currency, :tick_size, :tick_value,
          :multiplier, :session_calendar_id, :base_asset, :quote_asset, :is_continuous, :provenance
        )
        on conflict (symbol, venue) do update set
          name = excluded.name,
          tick_size = excluded.tick_size,
          tick_value = excluded.tick_value,
          multiplier = excluded.multiplier,
          session_calendar_id = excluded.session_calendar_id,
          base_asset = excluded.base_asset,
          quote_asset = excluded.quote_asset,
          is_continuous = excluded.is_continuous,
          provenance = excluded.provenance
        {_INSTRUMENT_RETURNING}
        """,
        {
            "id": instrument.id,
            "symbol": instrument.symbol,
            "name": instrument.name,
            "asset_class": instrument.asset_class,
            "venue": instrument.venue,
            "currency": instrument.currency,
            "tick_size": instrument.tick_size,
            "tick_value": instrument.tick_value,
            "multiplier": instrument.multiplier,
            "session_calendar_id": instrument.session_calendar_id,
            "base_asset": instrument.base_asset,
            "quote_asset": instrument.quote_asset,
            "is_continuous": instrument.is_continuous,
            "provenance": instrument.provenance,
        },
    )
    if row is None:
        msg = "instrument upsert returned no row"
        raise RuntimeError(msg)
    return _instrument(row)


async def get_instrument(conn: AsyncConnection, instrument_id: UUID) -> Instrument | None:
    row = await fetch_one(
        conn,
        "select id, symbol, name, asset_class, venue, currency, tick_size, tick_value, multiplier, "
        "session_calendar_id, base_asset, quote_asset, is_continuous, provenance "
        "from instruments where id = :id",
        {"id": instrument_id},
    )
    return None if row is None else _instrument(row)


async def upsert_futures_contract(
    conn: AsyncConnection, contract: FuturesContract
) -> FuturesContract:
    row = await fetch_one(
        conn,
        """
        insert into futures_contracts (
          id, instrument_id, root, contract_code, exchange, contract_month, expiry_date,
          last_trade_date, last_trade_time_local, first_notice_date, tick_size, tick_value,
          point_multiplier, currency, session_calendar_id, settlement_type, settlement_time_local,
          is_active, provenance
        ) values (
          :id, :instrument_id, :root, :contract_code, :exchange, :contract_month, :expiry_date,
          :last_trade_date, :last_trade_time_local, :first_notice_date, :tick_size, :tick_value,
          :point_multiplier, :currency, :session_calendar_id, :settlement_type,
          :settlement_time_local, :is_active, :provenance
        )
        on conflict (contract_code) do update set
          instrument_id = excluded.instrument_id,
          tick_size = excluded.tick_size,
          tick_value = excluded.tick_value,
          point_multiplier = excluded.point_multiplier,
          is_active = excluded.is_active,
          provenance = excluded.provenance
        returning id, instrument_id, root, contract_code, exchange, contract_month, expiry_date,
                  last_trade_date, last_trade_time_local, first_notice_date, tick_size, tick_value,
                  point_multiplier, currency, session_calendar_id, settlement_type,
                  settlement_time_local, is_active, provenance
        """,
        {
            "id": contract.id,
            "instrument_id": contract.instrument_id,
            "root": contract.root,
            "contract_code": contract.contract_code,
            "exchange": contract.exchange,
            "contract_month": contract.contract_month,
            "expiry_date": contract.expiry_date,
            "last_trade_date": contract.last_trade_date,
            "last_trade_time_local": contract.last_trade_time_local,
            "first_notice_date": contract.first_notice_date,
            "tick_size": contract.tick_size,
            "tick_value": contract.tick_value,
            "point_multiplier": contract.point_multiplier,
            "currency": contract.currency,
            "session_calendar_id": contract.session_calendar_id,
            "settlement_type": contract.settlement_type,
            "settlement_time_local": contract.settlement_time_local,
            "is_active": contract.is_active,
            "provenance": contract.provenance,
        },
    )
    if row is None:
        msg = "futures contract upsert returned no row"
        raise RuntimeError(msg)
    return _contract(row)


def _contract(row: dict[str, object]) -> FuturesContract:
    expiry = row["expiry_date"]
    last_trade = row["last_trade_date"]
    notice = row["first_notice_date"]
    last_time = row["last_trade_time_local"]
    settle = row["settlement_time_local"]
    return FuturesContract.model_validate(
        {
            "id": as_uuid(row["id"]),
            "instrument_id": as_uuid(row["instrument_id"]),
            "root": as_str(row["root"]),
            "contract_code": as_str(row["contract_code"]),
            "exchange": as_str(row["exchange"]),
            "contract_month": as_str(row["contract_month"]),
            "expiry_date": expiry if isinstance(expiry, date) else date.fromisoformat(str(expiry)),
            "last_trade_date": (
                last_trade if isinstance(last_trade, date) else date.fromisoformat(str(last_trade))
            ),
            "last_trade_time_local": last_time if isinstance(last_time, time) else None,
            "first_notice_date": notice if isinstance(notice, date) or notice is None else None,
            "tick_size": as_decimal(row["tick_size"]),
            "tick_value": as_decimal(row["tick_value"]),
            "point_multiplier": as_decimal(row["point_multiplier"]),
            "currency": as_str(row["currency"]),
            "session_calendar_id": as_str(row["session_calendar_id"]),
            "settlement_type": as_str(row["settlement_type"]),
            "settlement_time_local": settle if isinstance(settle, time) else None,
            "is_active": as_bool(row["is_active"]),
            "provenance": cast("Provenance", as_str(row["provenance"])),
        }
    )


async def upsert_roll_map(conn: AsyncConnection, roll: RollMapEntry) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into roll_maps (
          id, instrument_id, root, from_contract_code, to_contract_code, roll_date, method,
          adjustment, provenance
        ) values (
          :id, :instrument_id, :root, :from_contract_code, :to_contract_code, :roll_date,
          :method, :adjustment, :provenance
        )
        on conflict (instrument_id, from_contract_code, to_contract_code) do update set
          roll_date = excluded.roll_date,
          method = excluded.method,
          adjustment = excluded.adjustment
        returning id
        """,
        {
            "id": roll.id,
            "instrument_id": roll.instrument_id,
            "root": roll.root,
            "from_contract_code": roll.from_contract_code,
            "to_contract_code": roll.to_contract_code,
            "roll_date": roll.roll_date,
            "method": roll.method,
            "adjustment": roll.adjustment,
            "provenance": roll.provenance,
        },
    )
    if row is None:
        msg = "roll map upsert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


async def insert_watchlist(
    conn: AsyncConnection, *, owner_id: UUID, name: str, description: str | None = None
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into watchlists (owner_id, name, description)
        values (:owner_id, :name, :description)
        returning id
        """,
        {"owner_id": owner_id, "name": name, "description": description},
    )
    if row is None:
        msg = "watchlist insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


async def add_watchlist_item(
    conn: AsyncConnection,
    *,
    watchlist_id: UUID,
    instrument_id: UUID,
    contract_code: str | None = None,
    position: int = 0,
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into watchlist_items (watchlist_id, instrument_id, contract_code, position)
        values (:watchlist_id, :instrument_id, :contract_code, :position)
        on conflict (watchlist_id, instrument_id, contract_code) do update set
          position = excluded.position
        returning id
        """,
        {
            "watchlist_id": watchlist_id,
            "instrument_id": instrument_id,
            "contract_code": contract_code,
            "position": position,
        },
    )
    if row is None:
        msg = "watchlist item insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


async def list_watchlist_names(conn: AsyncConnection, owner_id: UUID) -> list[str]:
    rows = await fetch_all(
        conn,
        "select name from watchlists where owner_id = :owner_id order by name limit 100",
        {"owner_id": owner_id},
    )
    return [as_str(row["name"]) for row in rows]
