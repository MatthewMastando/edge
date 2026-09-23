"""Hypotheses, imports, account snapshots, usage ledger, budgets and settings."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from trading_core.storage.db import fetch_one
from trading_core.storage.repositories.common import as_decimal, as_json_dict, as_uuid, json_param

if TYPE_CHECKING:
    from pydantic import JsonValue
    from sqlalchemy.ext.asyncio import AsyncConnection


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None:
        msg = "month bounds require a timezone-aware datetime"
        raise ValueError(msg)
    start = datetime(now.year, now.month, 1, tzinfo=now.tzinfo)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1, tzinfo=now.tzinfo)
    else:
        end = datetime(now.year, now.month + 1, 1, tzinfo=now.tzinfo)
    return start, end


async def month_spend(
    conn: AsyncConnection, *, start: datetime, end: datetime, categories: str
) -> Decimal:
    row = await fetch_one(
        conn,
        """
        select coalesce(sum(coalesce(actual_cost_usd, reserved_cost_usd)), 0) as spent
        from usage_ledger
        where category = any(string_to_array(:categories, ','))
          and occurred_at >= :start
          and occurred_at < :end
        """,
        {"categories": categories, "start": start, "end": end},
    )
    if row is None:
        return Decimal(0)
    return as_decimal(row["spent"])


async def insert_usage(
    conn: AsyncConnection,
    *,
    run_id: UUID | None,
    job_id: UUID | None,
    category: str,
    provider: str,
    units: Decimal,
    unit_type: str,
    reserved_cost_usd: Decimal,
    metadata: dict[str, JsonValue] | None = None,
) -> int:
    row = await fetch_one(
        conn,
        """
        insert into usage_ledger (
          run_id, job_id, category, provider, units, unit_type, reserved_cost_usd, metadata
        ) values (
          :run_id, :job_id, :category, :provider, :units, :unit_type, :reserved_cost_usd,
          cast(:metadata as jsonb)
        )
        returning id
        """,
        {
            "run_id": run_id,
            "job_id": job_id,
            "category": category,
            "provider": provider,
            "units": units,
            "unit_type": unit_type,
            "reserved_cost_usd": reserved_cost_usd,
            "metadata": json_param(metadata or {}),
        },
    )
    if row is None:
        msg = "usage insert returned no row"
        raise RuntimeError(msg)
    return int(as_decimal(row["id"]))


async def reconcile_usage(conn: AsyncConnection, ledger_id: int, actual_cost_usd: Decimal) -> None:
    await fetch_one(
        conn,
        """
        update usage_ledger
        set actual_cost_usd = :actual, reserved_cost_usd = :actual
        where id = :id
        returning id
        """,
        {"id": ledger_id, "actual": actual_cost_usd},
    )


async def upsert_budget(
    conn: AsyncConnection, *, category: str, period_start: datetime, limit_usd: Decimal
) -> None:
    await fetch_one(
        conn,
        """
        insert into budgets (category, period_start, limit_usd)
        values (:category, :period_start, :limit_usd)
        on conflict (category, period_start) do update set limit_usd = excluded.limit_usd
        returning id
        """,
        {
            "category": category,
            "period_start": period_start.date(),
            "limit_usd": limit_usd,
        },
    )


async def get_setting(conn: AsyncConnection, key: str) -> dict[str, JsonValue] | None:
    row = await fetch_one(conn, "select value from settings where key = :key", {"key": key})
    if row is None:
        return None
    value = row["value"]
    if isinstance(value, dict):
        return as_json_dict(value)
    return {"value": as_json_dict({"value": value}).get("value")}


async def set_setting(
    conn: AsyncConnection, *, key: str, value: JsonValue, description: str | None = None
) -> None:
    await fetch_one(
        conn,
        """
        insert into settings (key, value, description)
        values (:key, cast(:value as jsonb), :description)
        on conflict (key) do update set value = excluded.value, description = excluded.description
        returning key
        """,
        {"key": key, "value": json_param(value), "description": description},
    )


async def insert_hypothesis(
    conn: AsyncConnection,
    *,
    artifact_revision_id: UUID,
    instrument_id: UUID,
    stance: str,
    horizon: str,
    contract_code: str | None = None,
    entry: Decimal | None = None,
    invalidation: Decimal | None = None,
    target: Decimal | None = None,
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into hypotheses (
          artifact_revision_id, instrument_id, contract_code, stance, entry, invalidation,
          target, horizon
        ) values (
          :artifact_revision_id, :instrument_id, :contract_code, :stance, :entry, :invalidation,
          :target, :horizon
        )
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
        },
    )
    if row is None:
        msg = "hypothesis insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


async def insert_hypothesis_observation(
    conn: AsyncConnection,
    *,
    hypothesis_id: UUID,
    observed_at: datetime,
    price: Decimal,
    event: str,
    data_revision: str,
    observed_tz: str = "UTC",
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into hypothesis_observations (
          hypothesis_id, observed_at, observed_tz, price, event, data_revision
        ) values (
          :hypothesis_id, :observed_at, :observed_tz, :price, :event, :data_revision
        )
        returning id
        """,
        {
            "hypothesis_id": hypothesis_id,
            "observed_at": observed_at,
            "observed_tz": observed_tz,
            "price": price,
            "event": event,
            "data_revision": data_revision,
        },
    )
    if row is None:
        msg = "hypothesis observation insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


async def insert_import_batch(
    conn: AsyncConnection, *, owner_id: UUID, filename: str, mapping_preset: dict[str, JsonValue]
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into import_batches (owner_id, filename, mapping_preset)
        values (:owner_id, :filename, cast(:mapping_preset as jsonb))
        returning id
        """,
        {
            "owner_id": owner_id,
            "filename": filename,
            "mapping_preset": json_param(mapping_preset),
        },
    )
    if row is None:
        msg = "import batch insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


async def insert_fill(
    conn: AsyncConnection,
    *,
    batch_id: UUID,
    source_row_number: int,
    source_row_hash: str,
    symbol_raw: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
    currency: str,
    fill_time: datetime,
    fill_tz: str,
    instrument_id: UUID | None = None,
    contract_code: str | None = None,
    fees: Decimal = Decimal(0),
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into imported_fills (
          batch_id, source_row_number, source_row_hash, instrument_id, symbol_raw, contract_code,
          side, quantity, price, fees, currency, fill_time, fill_tz
        ) values (
          :batch_id, :source_row_number, :source_row_hash, :instrument_id, :symbol_raw,
          :contract_code, :side, :quantity, :price, :fees, :currency, :fill_time, :fill_tz
        )
        on conflict (source_row_hash) do nothing
        returning id
        """,
        {
            "batch_id": batch_id,
            "source_row_number": source_row_number,
            "source_row_hash": source_row_hash,
            "instrument_id": instrument_id,
            "symbol_raw": symbol_raw,
            "contract_code": contract_code,
            "side": side,
            "quantity": quantity,
            "price": price,
            "fees": fees,
            "currency": currency,
            "fill_time": fill_time,
            "fill_tz": fill_tz,
        },
    )
    if row is None:
        existing = await fetch_one(
            conn,
            "select id from imported_fills where source_row_hash = :source_row_hash",
            {"source_row_hash": source_row_hash},
        )
        if existing is None:
            msg = "fill insert conflicted without a row"
            raise RuntimeError(msg)
        return as_uuid(existing["id"])
    return as_uuid(row["id"])


async def insert_account_snapshot(
    conn: AsyncConnection,
    *,
    owner_id: UUID,
    as_of: datetime,
    as_of_tz: str,
    source: str,
    currency: str,
    cash_balance: Decimal | None = None,
    snapshot_id: UUID | None = None,
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into account_snapshots (
          id, owner_id, as_of, as_of_tz, source, currency, cash_balance
        ) values (
          :id, :owner_id, :as_of, :as_of_tz, :source, :currency, :cash_balance
        )
        returning id
        """,
        {
            "id": snapshot_id or uuid4(),
            "owner_id": owner_id,
            "as_of": as_of,
            "as_of_tz": as_of_tz,
            "source": source,
            "currency": currency,
            "cash_balance": cash_balance,
        },
    )
    if row is None:
        msg = "account snapshot insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])
