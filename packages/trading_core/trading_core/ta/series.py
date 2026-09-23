"""Completed-bar preparation: ordering, tick alignment, gaps, rolls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from trading_core.domain.common import TIMEFRAME_SECONDS, Timeframe
from trading_core.ta.calendar import locate_session, next_trading_open
from trading_core.ta.interfaces import DetectorInput, InsufficientDataError

if TYPE_CHECKING:
    from decimal import Decimal

    from trading_core.domain.market import Bar

GapKind = Literal["ok", "session", "missing", "roll"]


def bar_step(timeframe: Timeframe) -> timedelta:
    return timedelta(seconds=TIMEFRAME_SECONDS[timeframe])


def bar_close_time(bar: Bar) -> datetime:
    return bar.origin_time + bar_step(bar.timeframe)


def is_tick_aligned(price: Decimal, tick: Decimal) -> bool:
    return price % tick == 0


@dataclass(frozen=True)
class PreparedSeries:
    """Bars the detectors are allowed to read.

    ``gaps[i]`` describes the relationship between ``bars[i]`` and ``bars[i + 1]``.
    ``ok`` means the next bar starts exactly one timeframe later. ``session`` is a scheduled
    close. ``missing`` is a hole inside a session. ``roll`` is a contract change or an explicit
    roll timestamp, even when the clocks happen to be adjacent.
    """

    bars: tuple[Bar, ...]
    gaps: tuple[GapKind, ...]
    tick: Decimal
    dropped_incomplete: bool

    def consecutive(self, start: int, end: int) -> bool:
        """True when every gap in ``[start, end)`` is ``ok`` (``end`` is exclusive)."""
        return all(self.gaps[i] == "ok" for i in range(start, end))


def tick_size(data: DetectorInput) -> Decimal:
    instrument_tick = data.instrument.tick_size
    if data.contract is not None and data.contract.tick_size != instrument_tick:
        msg = "instrument and contract tick sizes differ"
        raise ValueError(msg)
    if instrument_tick <= 0:
        msg = "tick size must be positive"
        raise ValueError(msg)
    return instrument_tick


def prepare(data: DetectorInput, roll_times: list[datetime]) -> PreparedSeries:
    bars = list(data.bars.bars)
    if not bars:
        raise InsufficientDataError("no bars")
    bars.sort(key=lambda bar: bar.origin_time)
    tick = tick_size(data)
    _validate_identity(data, bars)
    dropped = _drop_trailing_incomplete(bars)
    _validate_bars(data, bars, tick)
    gaps = tuple(
        _classify_gap(data, bars[i], bars[i + 1], roll_times) for i in range(len(bars) - 1)
    )
    return PreparedSeries(bars=tuple(bars), gaps=gaps, tick=tick, dropped_incomplete=dropped)


def _validate_identity(data: DetectorInput, bars: list[Bar]) -> None:
    seen: set[datetime] = set()
    for bar in bars:
        if bar.instrument_id != data.instrument.id:
            msg = "bar instrument does not match detector input"
            raise ValueError(msg)
        if bar.timeframe != data.bars.timeframe:
            msg = "mixed timeframes in one series"
            raise ValueError(msg)
        if bar.data_revision != data.bars.data_revision:
            msg = "mixed data revisions in one series"
            raise ValueError(msg)
        if bar.provenance != data.bars.provenance:
            msg = "mixed provenance in one series"
            raise ValueError(msg)
        if bar.origin_time in seen:
            msg = f"duplicate bar origin {bar.origin_time.isoformat()}"
            raise InsufficientDataError(msg)
        seen.add(bar.origin_time)


def _drop_trailing_incomplete(bars: list[Bar]) -> bool:
    if not bars[-1].is_complete:
        bars.pop()
        if not bars:
            raise InsufficientDataError("no completed bars")
        dropped = True
    else:
        dropped = False
    for bar in bars:
        if not bar.is_complete:
            msg = "incomplete bar before the end of the series"
            raise InsufficientDataError(msg)
    return dropped


def _validate_bars(data: DetectorInput, bars: list[Bar], tick: Decimal) -> None:
    for bar in bars:
        _validate_ohlc(bar, tick)
        if locate_session(data.calendar, bar.origin_time) is None:
            msg = f"bar {bar.origin_time.isoformat()} falls outside the session calendar"
            raise InsufficientDataError(msg)


def _validate_ohlc(bar: Bar, tick: Decimal) -> None:
    for label, price in (
        ("open", bar.open),
        ("high", bar.high),
        ("low", bar.low),
        ("close", bar.close),
    ):
        if not is_tick_aligned(price, tick):
            msg = f"bar {bar.origin_time.isoformat()} {label} is not tick-aligned"
            raise InsufficientDataError(msg)
    if bar.high < bar.low or bar.high < bar.open or bar.high < bar.close:
        msg = f"bar {bar.origin_time.isoformat()} high is below open, close, or low"
        raise ValueError(msg)
    if bar.low > bar.open or bar.low > bar.close:
        msg = f"bar {bar.origin_time.isoformat()} low is above open or close"
        raise ValueError(msg)
    if bar.volume < 0:
        msg = f"bar {bar.origin_time.isoformat()} has negative volume"
        raise ValueError(msg)


def _classify_gap(
    data: DetectorInput, left: Bar, right: Bar, roll_times: list[datetime]
) -> GapKind:
    if _is_roll(left, right, roll_times):
        return "roll"
    step = bar_step(left.timeframe)
    if right.origin_time - left.origin_time == step:
        return "ok"
    located = locate_session(data.calendar, left.origin_time)
    if located is None:
        return "missing"
    _session_date, _opens, closes = located
    if left.origin_time + step < closes:
        return "missing"
    nxt = next_trading_open(data.calendar, closes)
    if nxt is not None and right.origin_time == nxt:
        return "session"
    return "missing"


def _is_roll(left: Bar, right: Bar, roll_times: list[datetime]) -> bool:
    if (left.contract_code is None) != (right.contract_code is None):
        msg = "contract code disappears across adjacent bars"
        raise InsufficientDataError(msg)
    if left.contract_code != right.contract_code:
        return True
    return any(left.origin_time < roll_time <= right.origin_time for roll_time in roll_times)


def has_gap(prepared: PreparedSeries, kind: GapKind) -> bool:
    return kind in prepared.gaps


def contract_of(bar: Bar) -> str | None:
    return bar.contract_code
