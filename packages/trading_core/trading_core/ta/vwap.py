"""Session VWAP and optional anchored VWAP.

With trade prints, VWAP is cumulative price times size. Without them it is cumulative
typical price times bar volume. That bar form is candle VWAP, not volume-at-price.
The sum resets at each session and at each contract roll. A missing bar is rejected because
the absent volume is not zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from trading_core.ta.calendar import locate_session
from trading_core.ta.interfaces import InsufficientDataError
from trading_core.ta.profile import assert_trade_coverage
from trading_core.ta.series import PreparedSeries, bar_close_time
from trading_core.ta.wilder import require_no_missing

if TYPE_CHECKING:
    from datetime import datetime

    from trading_core.domain.instruments import SessionCalendar
    from trading_core.domain.market import Trade

Source = Literal["trades", "bar_typical"]


@dataclass(frozen=True)
class VwapPoint:
    index: int
    value: Decimal
    source: Source


def vwap_points(
    prepared: PreparedSeries,
    calendar: SessionCalendar,
    trades: list[Trade] | None,
    anchor_time: datetime | None,
) -> list[VwapPoint]:
    require_no_missing(prepared, "VWAP")
    if trades is not None:
        assert_trade_coverage(list(prepared.bars), trades)
        return _from_trades(prepared, calendar, trades, anchor_time)
    return _from_bars(prepared, calendar, anchor_time)


def _from_bars(
    prepared: PreparedSeries, calendar: SessionCalendar, anchor_time: datetime | None
) -> list[VwapPoint]:
    points: list[VwapPoint] = []
    cum_pv = Decimal(0)
    cum_volume = Decimal(0)
    active: tuple[object, ...] | None = None
    for index, bar in enumerate(prepared.bars):
        if anchor_time is not None and bar.origin_time < anchor_time:
            continue
        key = _bucket(prepared, calendar, index, anchor_time)
        if key != active:
            active = key
            cum_pv = Decimal(0)
            cum_volume = Decimal(0)
        cum_pv += ((bar.high + bar.low + bar.close) / Decimal(3)) * bar.volume
        cum_volume += bar.volume
        if cum_volume == 0:
            continue
        points.append(VwapPoint(index, cum_pv / cum_volume, "bar_typical"))
    if not points:
        msg = "VWAP has no volume"
        raise InsufficientDataError(msg)
    return points


def _from_trades(
    prepared: PreparedSeries,
    calendar: SessionCalendar,
    trades: list[Trade],
    anchor_time: datetime | None,
) -> list[VwapPoint]:
    ordered = sorted(trades, key=lambda trade: (trade.trade_time, trade.sequence))
    points: list[VwapPoint] = []
    cum_pv = Decimal(0)
    cum_volume = Decimal(0)
    active: tuple[object, ...] | None = None
    cursor = 0
    for index, bar in enumerate(prepared.bars):
        close = bar_close_time(bar)
        if anchor_time is not None and bar.origin_time < anchor_time:
            while cursor < len(ordered) and ordered[cursor].trade_time < close:
                cursor += 1
            continue
        key = _bucket(prepared, calendar, index, anchor_time)
        if key != active:
            active = key
            cum_pv = Decimal(0)
            cum_volume = Decimal(0)
        while cursor < len(ordered) and ordered[cursor].trade_time < close:
            trade = ordered[cursor]
            cursor += 1
            if trade.trade_time < bar.origin_time:
                continue
            if bar.contract_code is not None and trade.contract_code != bar.contract_code:
                continue
            cum_pv += trade.price * trade.size
            cum_volume += trade.size
        if cum_volume == 0:
            continue
        points.append(VwapPoint(index, cum_pv / cum_volume, "trades"))
    if not points:
        msg = "VWAP has no trade size"
        raise InsufficientDataError(msg)
    return points


def _bucket(
    prepared: PreparedSeries,
    calendar: SessionCalendar,
    index: int,
    anchor_time: datetime | None,
) -> tuple[object, ...]:
    bar = prepared.bars[index]
    if anchor_time is not None:
        return ("anchored", anchor_time, bar.contract_code)
    located = locate_session(calendar, bar.origin_time)
    if located is None:
        msg = f"bar {bar.origin_time.isoformat()} falls outside the session calendar"
        raise InsufficientDataError(msg)
    return (located[0], bar.contract_code)
