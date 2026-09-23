"""Freeze a thesis version and record what price did after that.

Simulated P&L is computed here and stored on the hypothesis. Imported fills are not touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from trading_core.automation.pnl import SIMULATED, simulated_pnl
from trading_core.data.adapter import BarsRequest, UnknownSymbolError
from trading_core.storage.repositories import automation as store
from trading_core.storage.repositories.common import (
    as_datetime,
    as_decimal,
    as_json_dict,
    as_str,
    as_uuid,
)

if TYPE_CHECKING:
    from uuid import UUID

    from pydantic import JsonValue
    from sqlalchemy.ext.asyncio import AsyncConnection

    from trading_core.data.adapter import MarketDataAdapter
    from trading_core.domain.thesis import Thesis

_TERMINAL = frozenset({"invalidated", "target_hit", "expired", "untriggered"})


@dataclass(frozen=True)
class PriceBar:
    origin_time: datetime
    origin_tz: str
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass
class PathResult:
    status: str
    entry_state: str
    subsequent_move: Decimal | None
    simulated_pnl: Decimal | None
    exit_kind: str | None
    observations: list[tuple[str, datetime, str, Decimal, str]] = field(default_factory=list)


def apply_price_path(
    *,
    stance: str,
    entry: Decimal | None,
    invalidation: Decimal | None,
    target: Decimal | None,
    frozen_at: datetime,
    status: str,
    entry_state: str,
    bars: list[PriceBar],
    multiplier: Decimal,
    cost: Decimal,
    data_revision: str,
) -> PathResult:
    """Walk bars after the freeze. Entry, invalidation and target are observed in order."""
    result = PathResult(
        status=status,
        entry_state=entry_state,
        subsequent_move=None,
        simulated_pnl=None,
        exit_kind=None,
    )
    later = [bar for bar in bars if bar.origin_time >= frozen_at]
    if not later:
        return result
    for bar in later:
        _apply_bar(
            result,
            bar,
            stance=stance,
            entry=entry,
            invalidation=invalidation,
            target=target,
            data_revision=data_revision,
        )
    last = later[-1]
    reference = entry if result.entry_state == "triggered" and entry is not None else later[0].close
    result.subsequent_move = last.close - reference
    result.observations.append(
        ("checkpoint", last.origin_time, last.origin_tz, last.close, data_revision)
    )
    if result.entry_state == "triggered" and entry is not None and stance in {"bullish", "bearish"}:
        exit_price, result.exit_kind = _exit_price(result.status, invalidation, target, last.close)
        result.simulated_pnl = simulated_pnl(
            stance=stance,
            entry=entry,
            exit_price=exit_price,
            multiplier=multiplier,
            cost=cost,
        )
    return result


def _apply_bar(
    result: PathResult,
    bar: PriceBar,
    *,
    stance: str,
    entry: Decimal | None,
    invalidation: Decimal | None,
    target: Decimal | None,
    data_revision: str,
) -> None:
    if result.status in _TERMINAL:
        return
    if entry is not None and result.entry_state == "untriggered" and bar.low <= entry <= bar.high:
        result.entry_state = "triggered"
        if result.status == "open":
            result.status = "triggered"
        result.observations.append(
            ("entry_triggered", bar.origin_time, bar.origin_tz, entry, data_revision)
        )
    if invalidation is not None and _invalidated(stance, bar.close, invalidation):
        result.status = "invalidated"
        result.observations.append(
            ("invalidation_hit", bar.origin_time, bar.origin_tz, bar.close, data_revision)
        )
        return
    if target is not None and _target_hit(stance, bar, target):
        result.status = "target_hit"
        result.observations.append(
            ("target_hit", bar.origin_time, bar.origin_tz, target, data_revision)
        )


def _invalidated(stance: str, close: Decimal, invalidation: Decimal) -> bool:
    if stance == "bullish":
        return close < invalidation
    if stance == "bearish":
        return close > invalidation
    return False


def _target_hit(stance: str, bar: PriceBar, target: Decimal) -> bool:
    if stance == "bullish":
        return bar.high >= target
    if stance == "bearish":
        return bar.low <= target
    return False


def _exit_price(
    status: str, invalidation: Decimal | None, target: Decimal | None, close: Decimal
) -> tuple[Decimal, str]:
    if status == "invalidated" and invalidation is not None:
        return invalidation, "invalidation"
    if status == "target_hit" and target is not None:
        return target, "target"
    return close, "latest_close"


async def freeze_thesis(conn: AsyncConnection, thesis: Thesis, revision_id: UUID) -> UUID:
    """One frozen row per immutable revision. A second call returns the existing id."""
    assumptions: dict[str, JsonValue] = {
        "label": SIMULATED,
        "fill": "bar_range_includes_entry",
        "contracts": 1,
        "cost": "0",
    }
    return await store.freeze_hypothesis(
        conn,
        artifact_revision_id=revision_id,
        instrument_id=thesis.instrument_id,
        contract_code=thesis.contract_code,
        stance=thesis.stance,
        entry=thesis.plan.entry,
        invalidation=thesis.plan.invalidation,
        target=thesis.plan.target,
        horizon=thesis.horizon,
        expires_at=thesis.expires_at,
        assumptions=assumptions,
    )


async def observe_open(conn: AsyncConnection, adapter: MarketDataAdapter) -> int:
    """Update open hypotheses from fixture or live bars. Returns how many rows changed."""
    rows = await store.list_hypotheses_to_check(conn)
    changed = 0
    for row in rows:
        if await _observe_one(conn, adapter, row):
            changed += 1
    return changed


async def _observe_one(
    conn: AsyncConnection, adapter: MarketDataAdapter, row: dict[str, object]
) -> bool:
    symbol = as_str(row["contract_code"] or row["symbol"])
    try:
        series = await adapter.get_bars(BarsRequest(symbol=symbol, timeframe="5m", limit=5000))
    except UnknownSymbolError:
        return False
    bars = [
        PriceBar(
            origin_time=bar.origin_time,
            origin_tz=bar.origin_tz,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
        for bar in series.bars
        if bar.is_complete
    ]
    entry = _money(row["entry"])
    invalidation = _money(row["invalidation"])
    target = _money(row["target"])
    assumptions = _assumptions(row["assumptions"])
    cost = _cost(assumptions)
    path = apply_price_path(
        stance=as_str(row["stance"]),
        entry=entry,
        invalidation=invalidation,
        target=target,
        frozen_at=as_datetime(row["frozen_at"]),
        status=as_str(row["status"]),
        entry_state=as_str(row["entry_state"]),
        bars=bars,
        multiplier=as_decimal(row["multiplier"]),
        cost=cost,
        data_revision=series.data_revision,
    )
    if path.subsequent_move is None and path.status == as_str(row["status"]):
        return False
    for event, observed_at, observed_tz, price, revision in path.observations:
        await store.insert_observation_once(
            conn,
            hypothesis_id=as_uuid(row["id"]),
            observed_at=observed_at,
            observed_tz=observed_tz,
            price=price,
            event=event,
            data_revision=revision,
            note=None,
        )
    if path.exit_kind is not None:
        assumptions["exit"] = path.exit_kind
        assumptions["label"] = SIMULATED
    await store.update_hypothesis_outcome(
        conn,
        hypothesis_id=as_uuid(row["id"]),
        status=path.status,
        entry_state=path.entry_state,
        subsequent_move=path.subsequent_move,
        simulated_pnl=path.simulated_pnl,
        simulated_pnl_currency=as_str(row["currency"]),
        assumptions=assumptions,
    )
    return True


def _money(value: object) -> Decimal | None:
    if value is None:
        return None
    return as_decimal(value)


def _assumptions(value: object) -> dict[str, JsonValue]:
    if isinstance(value, dict):
        return as_json_dict(value)
    return {"label": SIMULATED}


def _cost(assumptions: dict[str, JsonValue]) -> Decimal:
    raw = assumptions.get("cost", "0")
    if isinstance(raw, str):
        return Decimal(raw)
    if isinstance(raw, int | float):
        return Decimal(str(raw))
    return Decimal(0)


def reference_now() -> datetime:
    return datetime.now(UTC)
