"""Wilder ATR(14) and RSI(14).

Both seed with a simple average of the first ``period`` observations, then smooth as
``(period - 1) * prior + current) / period``. For the default period that is
``(13 * prior + current) / 14``.

RSI observations are close-to-close gains and losses. The first average uses changes
1..14, so the first RSI is on bar index 14 (the 15th bar). ATR observations are true
ranges with the same alignment: TR starts at bar 1, and the first ATR is the mean of
TR[1]..TR[14], published on bar index 14.

RSI is 100 when average loss is zero and average gain is positive, 0 when only average
gain is zero, and 50 when both are zero.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from trading_core.ta.constants import ATR_PERIOD, PUBLISHED_PLACES, RSI_PERIOD
from trading_core.ta.interfaces import InsufficientDataError

if TYPE_CHECKING:
    from trading_core.domain.market import Bar
    from trading_core.ta.series import GapKind, PreparedSeries


@dataclass(frozen=True)
class IndicatorPoint:
    index: int
    value: Decimal


def wilder_rsi(closes: list[Decimal], period: int = RSI_PERIOD) -> list[IndicatorPoint]:
    if period < 1:
        msg = "RSI period must be positive"
        raise ValueError(msg)
    if len(closes) < period + 1:
        msg = (
            f"RSI({period}) needs {period + 1} completed bars ({period} changes); got {len(closes)}"
        )
        raise InsufficientDataError(msg)
    gains, losses = _changes(closes)
    avg_gain = sum(gains[:period], start=Decimal(0)) / Decimal(period)
    avg_loss = sum(losses[:period], start=Decimal(0)) / Decimal(period)
    points = [IndicatorPoint(period, _rsi(avg_gain, avg_loss))]
    rest = zip(gains[period:], losses[period:], strict=True)
    for offset, (gain, loss) in enumerate(rest, start=period + 1):
        avg_gain = ((Decimal(period - 1) * avg_gain) + gain) / Decimal(period)
        avg_loss = ((Decimal(period - 1) * avg_loss) + loss) / Decimal(period)
        points.append(IndicatorPoint(offset, _rsi(avg_gain, avg_loss)))
    return points


def wilder_atr(bars: list[Bar], period: int = ATR_PERIOD) -> list[IndicatorPoint]:
    """ATR on one contiguous segment. ``bars`` must already exclude roll and missing breaks."""
    if period < 1:
        msg = "ATR period must be positive"
        raise ValueError(msg)
    if len(bars) < period + 1:
        msg = (
            f"ATR({period}) needs {period + 1} completed bars "
            f"({period} true ranges); got {len(bars)}"
        )
        raise InsufficientDataError(msg)
    ranges = _true_ranges(bars)
    seed = sum(ranges[:period], start=Decimal(0)) / Decimal(period)
    points = [IndicatorPoint(period, seed)]
    current = seed
    for offset, true_range in enumerate(ranges[period:], start=period + 1):
        current = ((Decimal(period - 1) * current) + true_range) / Decimal(period)
        points.append(IndicatorPoint(offset, current))
    return points


def rsi_by_index(
    prepared: PreparedSeries,
    *,
    period: int,
    split_on: frozenset[GapKind],
    allow_short: bool = False,
) -> dict[int, Decimal]:
    return _map_segments(
        prepared, period=period, split_on=split_on, kind="rsi", allow_short=allow_short
    )


def atr_by_index(
    prepared: PreparedSeries,
    *,
    period: int,
    split_on: frozenset[GapKind],
    allow_short: bool = False,
) -> dict[int, Decimal]:
    return _map_segments(
        prepared, period=period, split_on=split_on, kind="atr", allow_short=allow_short
    )


def require_no_missing(prepared: PreparedSeries, what: str) -> None:
    if "missing" in prepared.gaps:
        msg = f"{what} refuses to compute across a missing bar"
        raise InsufficientDataError(msg)


def publish(value: Decimal) -> Decimal:
    return value.quantize(PUBLISHED_PLACES)


def _map_segments(
    prepared: PreparedSeries,
    *,
    period: int,
    split_on: frozenset[GapKind],
    kind: str,
    allow_short: bool,
) -> dict[int, Decimal]:
    points: dict[int, Decimal] = {}
    produced = False
    short = False
    for start, end in _segments(len(prepared.bars), prepared.gaps, split_on):
        segment = list(prepared.bars[start:end])
        if len(segment) < period + 1:
            short = True
            continue
        if kind == "rsi":
            computed = wilder_rsi([bar.close for bar in segment], period)
        else:
            computed = wilder_atr(segment, period)
        produced = True
        for point in computed:
            points[start + point.index] = point.value
    if produced or allow_short:
        return points
    if short:
        label = "RSI" if kind == "rsi" else "ATR"
        msg = f"{label}({period}) warm-up is not met on any contiguous segment"
        raise InsufficientDataError(msg)
    msg = f"no bars for {kind}"
    raise InsufficientDataError(msg)


def _segments(
    count: int, gaps: tuple[GapKind, ...], split_on: frozenset[GapKind]
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for index, gap in enumerate(gaps):
        if gap in split_on:
            spans.append((start, index + 1))
            start = index + 1
    spans.append((start, count))
    return spans


def _changes(closes: list[Decimal]) -> tuple[list[Decimal], list[Decimal]]:
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for previous, current in itertools.pairwise(closes):
        delta = current - previous
        gains.append(delta if delta > 0 else Decimal(0))
        losses.append(-delta if delta < 0 else Decimal(0))
    return gains, losses


def _rsi(avg_gain: Decimal, avg_loss: Decimal) -> Decimal:
    if avg_gain == 0 and avg_loss == 0:
        return Decimal(50)
    if avg_loss == 0:
        return Decimal(100)
    if avg_gain == 0:
        return Decimal(0)
    return Decimal(100) * avg_gain / (avg_gain + avg_loss)


def _true_ranges(bars: list[Bar]) -> list[Decimal]:
    ranges: list[Decimal] = []
    for previous, current in itertools.pairwise(bars):
        ranges.append(_true_range(current, previous.close))
    return ranges


def _true_range(bar: Bar, previous_close: Decimal) -> Decimal:
    return max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close))
