"""Liquidity sweeps of pivots, equal-extreme pools, and session levels.

A buy-side sweep trades at least one tick beyond a high and closes back below it on the
same candle. A sell-side sweep does the reverse. The level must already be confirmed
before the sweep bar opens. Taking the wick without the close is not a sweep. Each level
is consumed by its first sweep so a later bar cannot open a second event for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from trading_core.ta.envelope import decimal_str, time_str
from trading_core.ta.series import PreparedSeries, bar_close_time
from trading_core.ta.session_levels import SessionLevel, detect_session_levels

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from pydantic import JsonValue

    from trading_core.domain.common import Direction
    from trading_core.domain.instruments import SessionCalendar
    from trading_core.ta.swings import Pool, Swing

SweepSide = Literal["buy_side", "sell_side"]


@dataclass(frozen=True)
class KnownLevel:
    source: str
    price: Decimal
    formed_at: datetime
    confirmation_time: datetime
    contract_code: str | None
    side: SweepSide


@dataclass(frozen=True)
class SweepHit:
    level: KnownLevel
    excursion: Decimal


@dataclass(frozen=True)
class Sweep:
    index: int
    hits: tuple[SweepHit, ...]
    direction: Direction
    contract_code: str | None


def collect_levels(
    prepared: PreparedSeries,
    calendar: SessionCalendar,
    swings: list[Swing],
    pools: list[Pool],
) -> list[KnownLevel]:
    levels: list[KnownLevel] = []
    bars = prepared.bars
    for swing in swings:
        if swing.is_high:
            levels.append(
                KnownLevel(
                    source="swing_high",
                    price=bars[swing.index].high,
                    formed_at=swing.origin_time,
                    confirmation_time=swing.confirmation_time,
                    contract_code=swing.contract_code,
                    side="buy_side",
                )
            )
        if swing.is_low:
            levels.append(
                KnownLevel(
                    source="swing_low",
                    price=bars[swing.index].low,
                    formed_at=swing.origin_time,
                    confirmation_time=swing.confirmation_time,
                    contract_code=swing.contract_code,
                    side="sell_side",
                )
            )
    for pool in pools:
        formed = bars[pool.formed_index].origin_time
        confirmed = bar_close_time(bars[pool.confirmation_index])
        levels.append(
            KnownLevel(
                source="pool_high" if pool.side == "high" else "pool_low",
                price=pool.level,
                formed_at=formed,
                confirmation_time=confirmed,
                contract_code=pool.contract_code,
                side="buy_side" if pool.side == "high" else "sell_side",
            )
        )
    for session_level in detect_session_levels(prepared, calendar):
        levels.extend(_session_levels(session_level))
    return levels


def find_sweeps(prepared: PreparedSeries, levels: list[KnownLevel], tick: Decimal) -> list[Sweep]:
    consumed: set[tuple[object, ...]] = set()
    found: list[Sweep] = []
    for index, bar in enumerate(prepared.bars):
        hits: list[SweepHit] = []
        for level in levels:
            identity = _identity(level)
            if identity in consumed:
                continue
            if level.contract_code != bar.contract_code:
                continue
            if level.confirmation_time > bar.origin_time:
                continue
            hit = _hit(level, bar.high, bar.low, bar.close, tick)
            if hit is None:
                continue
            consumed.add(identity)
            hits.append(hit)
        if not hits:
            continue
        found.append(
            Sweep(
                index=index,
                hits=tuple(hits),
                direction=_direction(hits),
                contract_code=bar.contract_code,
            )
        )
    return found


def sweep_details(prepared: PreparedSeries, sweep: Sweep) -> dict[str, JsonValue]:
    bar = prepared.bars[sweep.index]
    hits: list[JsonValue] = []
    for hit in sweep.hits:
        hits.append(
            {
                "source": hit.level.source,
                "price": decimal_str(hit.level.price),
                "formed_at": time_str(hit.level.formed_at),
                "excursion": decimal_str(hit.excursion),
                "side": hit.level.side,
            }
        )
    return {"sweep_index": sweep.index, "close": decimal_str(bar.close), "hits": hits}


def _session_levels(level: SessionLevel) -> list[KnownLevel]:
    if level.kind == "rth":
        return [
            KnownLevel(
                source="pdh",
                price=level.high,
                formed_at=level.high_time,
                confirmation_time=level.confirmation_time,
                contract_code=level.contract_code,
                side="buy_side",
            ),
            KnownLevel(
                source="pdl",
                price=level.low,
                formed_at=level.low_time,
                confirmation_time=level.confirmation_time,
                contract_code=level.contract_code,
                side="sell_side",
            ),
        ]
    return [
        KnownLevel(
            source="onh",
            price=level.high,
            formed_at=level.high_time,
            confirmation_time=level.confirmation_time,
            contract_code=level.contract_code,
            side="buy_side",
        ),
        KnownLevel(
            source="onl",
            price=level.low,
            formed_at=level.low_time,
            confirmation_time=level.confirmation_time,
            contract_code=level.contract_code,
            side="sell_side",
        ),
    ]


def _hit(
    level: KnownLevel, high: Decimal, low: Decimal, close: Decimal, tick: Decimal
) -> SweepHit | None:
    if level.side == "buy_side":
        if high >= level.price + tick and close < level.price:
            return SweepHit(level=level, excursion=high - level.price)
        return None
    if low <= level.price - tick and close > level.price:
        return SweepHit(level=level, excursion=level.price - low)
    return None


def _direction(hits: list[SweepHit]) -> Direction:
    sides = {hit.level.side for hit in hits}
    if sides == {"buy_side"}:
        return "bearish"
    if sides == {"sell_side"}:
        return "bullish"
    return "neutral"


def _identity(level: KnownLevel) -> tuple[object, ...]:
    return (level.source, level.price, level.formed_at, level.contract_code, level.side)
