"""Market snapshots and deterministic TA rows."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from trading_core.storage.db import fetch_all, fetch_one
from trading_core.storage.repositories.common import as_decimal, as_uuid, json_param, uuid_array

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection

    from trading_core.domain.market import MarketSnapshot
    from trading_core.domain.ta import TAEvent, TAFeature, TAFeatureTransition


async def insert_snapshot(conn: AsyncConnection, snapshot: MarketSnapshot, *, backend: str) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into market_snapshots (
          id, instrument_id, contract_code, timeframe, kind, range_start, range_end, as_of,
          as_of_tz, provider, provenance, data_revision, storage_backend, storage_key, row_count,
          content_hash, coverage_note
        ) values (
          :id, :instrument_id, :contract_code, :timeframe, :kind, :range_start, :range_end, :as_of,
          :as_of_tz, :provider, :provenance, :data_revision, :storage_backend, :storage_key,
          :row_count, :content_hash, :coverage_note
        )
        on conflict (storage_key) do update set content_hash = excluded.content_hash
        returning id
        """,
        {
            "id": snapshot.id,
            "instrument_id": snapshot.instrument_id,
            "contract_code": snapshot.contract_code,
            "timeframe": snapshot.timeframe,
            "kind": snapshot.kind,
            "range_start": snapshot.range_start,
            "range_end": snapshot.range_end,
            "as_of": snapshot.as_of,
            "as_of_tz": snapshot.as_of_tz,
            "provider": snapshot.provider,
            "provenance": snapshot.provenance,
            "data_revision": snapshot.data_revision,
            "storage_backend": backend,
            "storage_key": snapshot.storage_key,
            "row_count": snapshot.row_count,
            "content_hash": snapshot.content_hash,
            "coverage_note": snapshot.coverage_note,
        },
    )
    if row is None:
        msg = "snapshot insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


async def insert_feature(conn: AsyncConnection, feature: TAFeature) -> UUID:
    payload = feature.model_dump(mode="json")
    row = await fetch_one(
        conn,
        """
        insert into ta_features (
          id, detector, calc_version, instrument_id, contract_code, timeframe, session,
          session_calendar_id, session_calendar_version, direction, state, origin_time, origin_tz,
          confirmation_time, confirmation_tz, as_of, as_of_tz, levels, parameters, details,
          warnings, snapshot_id, data_revision, provenance
        ) values (
          :id, :detector, :calc_version, :instrument_id, :contract_code, :timeframe, :session,
          :session_calendar_id, :session_calendar_version, :direction, :state, :origin_time,
          :origin_tz, :confirmation_time, :confirmation_tz, :as_of, :as_of_tz,
          cast(:levels as jsonb), cast(:parameters as jsonb), cast(:details as jsonb),
          cast(:warnings as jsonb), :snapshot_id, :data_revision, :provenance
        )
        on conflict (id) do nothing
        returning id
        """,
        {
            "id": feature.id,
            "detector": feature.detector,
            "calc_version": feature.calc_version,
            "instrument_id": feature.instrument_id,
            "contract_code": feature.contract_code,
            "timeframe": feature.timeframe,
            "session": feature.session,
            "session_calendar_id": feature.session_calendar_id,
            "session_calendar_version": feature.session_calendar_version,
            "direction": feature.direction,
            "state": feature.state,
            "origin_time": feature.origin_time,
            "origin_tz": feature.origin_tz,
            "confirmation_time": feature.confirmation_time,
            "confirmation_tz": feature.confirmation_tz,
            "as_of": feature.as_of,
            "as_of_tz": feature.as_of_tz,
            "levels": json_param(payload["levels"]),
            "parameters": json_param(payload["parameters"]),
            "details": json_param(payload["details"]),
            "warnings": json_param(payload["warnings"]),
            "snapshot_id": feature.snapshot_id,
            "data_revision": feature.data_revision,
            "provenance": feature.provenance,
        },
    )
    if row is not None:
        return as_uuid(row["id"])
    return feature.id


async def insert_event(conn: AsyncConnection, event: TAEvent) -> None:
    payload = event.model_dump(mode="json")
    await fetch_one(
        conn,
        """
        insert into ta_events (
          id, feature_id, instrument_id, contract_code, timeframe, detector, calc_version,
          origin_time, data_revision, event_type, event_time, event_tz, direction, levels,
          details, provenance
        ) values (
          :id, :feature_id, :instrument_id, :contract_code, :timeframe, :detector, :calc_version,
          :origin_time, :data_revision, :event_type, :event_time, :event_tz, :direction,
          cast(:levels as jsonb), cast(:details as jsonb), :provenance
        )
        on conflict on constraint ta_events_idempotent_key do nothing
        returning id
        """,
        {
            "id": event.id,
            "feature_id": event.feature_id,
            "instrument_id": event.instrument_id,
            "contract_code": event.contract_code,
            "timeframe": event.timeframe,
            "detector": event.detector,
            "calc_version": event.calc_version,
            "origin_time": event.origin_time,
            "data_revision": event.data_revision,
            "event_type": event.event_type,
            "event_time": event.event_time,
            "event_tz": event.event_tz,
            "direction": event.direction,
            "levels": json_param(payload["levels"]),
            "details": json_param(payload["details"]),
            "provenance": event.provenance,
        },
    )


async def insert_transition(conn: AsyncConnection, transition: TAFeatureTransition) -> None:
    await fetch_one(
        conn,
        """
        insert into ta_feature_transitions (
          feature_id, from_state, to_state, bar_time, bar_tz, data_revision, details
        ) values (
          :feature_id, :from_state, :to_state, :bar_time, :bar_tz, :data_revision,
          cast(:details as jsonb)
        )
        on conflict (feature_id, to_state, bar_time, data_revision) do nothing
        returning id
        """,
        {
            "feature_id": transition.feature_id,
            "from_state": transition.from_state,
            "to_state": transition.to_state,
            "bar_time": transition.bar_time,
            "bar_tz": transition.bar_tz,
            "data_revision": transition.data_revision,
            "details": json_param(transition.model_dump(mode="json")["details"]),
        },
    )


def _level_prices(raw: object) -> set[Decimal]:
    parsed: object = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(parsed, list):
        return set()
    prices: set[Decimal] = set()
    for item in parsed:
        if isinstance(item, dict) and "price" in item:
            prices.add(as_decimal(item["price"]))
    return prices


async def feature_levels(
    conn: AsyncConnection, feature_ids: list[UUID]
) -> dict[UUID, set[Decimal]]:
    if not feature_ids:
        return {}
    rows = await fetch_all(
        conn,
        """
        select id, levels
        from ta_features
        where id = any(cast(string_to_array(:ids, ',') as uuid[]))
        """,
        {"ids": uuid_array(feature_ids)},
    )
    return {as_uuid(row["id"]): _level_prices(row["levels"]) for row in rows}


async def list_feature_ids(conn: AsyncConnection, feature_ids: list[UUID]) -> set[UUID]:
    if not feature_ids:
        return set()
    rows = await fetch_all(
        conn,
        "select id from ta_features where id = any(cast(string_to_array(:ids, ',') as uuid[]))",
        {"ids": uuid_array(feature_ids)},
    )
    return {as_uuid(row["id"]) for row in rows}


def snapshot_bounds(times: list[datetime]) -> tuple[datetime, datetime]:
    if not times:
        msg = "snapshot requires at least one timestamp"
        raise ValueError(msg)
    return min(times), max(times)
