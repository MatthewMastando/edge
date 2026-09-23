"""PDH/PDL and ONH/ONL from completed session windows.

PDH/PDL are the high and low of the RTH sub-window when the calendar has one, otherwise of
the full trading session. ONH/ONL are the high and low from the trading open until that RTH
open. Calendars without a separate RTH window do not invent an overnight range.

A window is confirmed only when every expected bar is present. A snapshot that starts late
skips that partial first window. A hole inside a window is missing data.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from trading_core.ta.calendar import expected_origins, locate_session, rth_bounds, trading_bounds
from trading_core.ta.interfaces import InsufficientDataError
from trading_core.ta.series import PreparedSeries, bar_close_time, bar_step

if TYPE_CHECKING:
    from datetime import date, datetime, timedelta
    from decimal import Decimal

    from trading_core.domain.instruments import SessionCalendar

LevelKind = Literal["rth", "overnight"]


@dataclass(frozen=True)
class SessionLevel:
    kind: LevelKind
    session_day: date
    origin_time: datetime
    confirmation_time: datetime
    timezone: str
    high: Decimal
    low: Decimal
    high_time: datetime
    low_time: datetime
    contract_code: str | None


def detect_session_levels(
    prepared: PreparedSeries, calendar: SessionCalendar
) -> list[SessionLevel]:
    """Confirmed day-range and overnight levels for every fully covered window in the series."""
    grouped = _group_sessions(prepared, calendar)
    levels: list[SessionLevel] = []
    for session_index, (session_day, indexes) in enumerate(grouped):
        trading = trading_bounds(calendar, session_day)
        if len(trading) != 1:
            msg = f"session {session_day.isoformat()} does not have one trading window"
            raise ValueError(msg)
        opens, closes = trading[0]
        rth = rth_bounds(calendar, session_day)
        is_first = session_index == 0
        is_last = session_index == len(grouped) - 1
        windows: list[tuple[datetime, datetime, LevelKind]]
        if rth is None:
            windows = [(opens, closes, "rth")]
        else:
            rth_open, rth_close = rth
            windows = [(rth_open, rth_close, "rth"), (opens, rth_open, "overnight")]
        for window_open, window_close, kind in windows:
            _append_if_full(
                levels,
                prepared,
                indexes,
                window_open,
                window_close,
                kind,
                session_day,
                calendar.timezone,
                is_first=is_first,
                is_last=is_last,
            )
    return levels


def session_has_overnight(calendar: SessionCalendar) -> bool:
    # Bounds depend on a date only for the clock conversion; the presence of a sub-window does not.
    return any(window.kind == "sub_session" for window in calendar.windows)


def _group_sessions(
    prepared: PreparedSeries, calendar: SessionCalendar
) -> list[tuple[date, list[int]]]:
    groups: list[tuple[date, list[int]]] = []
    current_key: date | None = None
    bucket: list[int] = []
    for index, bar in enumerate(prepared.bars):
        located = locate_session(calendar, bar.origin_time)
        if located is None:
            msg = f"bar {bar.origin_time.isoformat()} falls outside the session calendar"
            raise InsufficientDataError(msg)
        session_date, _open, _close = located
        if current_key is None:
            current_key = session_date
        if session_date != current_key:
            groups.append((current_key, bucket))
            current_key = session_date
            bucket = []
        bucket.append(index)
    if current_key is not None:
        groups.append((current_key, bucket))
    return groups


def _append_if_full(
    levels: list[SessionLevel],
    prepared: PreparedSeries,
    indexes: list[int],
    window_open: datetime,
    window_close: datetime,
    kind: LevelKind,
    session_day: date,
    timezone: str,
    *,
    is_first: bool,
    is_last: bool,
) -> None:
    step = bar_step(prepared.bars[0].timeframe)
    coverage = _coverage(
        prepared,
        indexes,
        window_open,
        window_close,
        step,
        is_first=is_first,
        is_last=is_last,
    )
    if coverage != "full":
        return
    present = [
        index for index in indexes if window_open <= prepared.bars[index].origin_time < window_close
    ]
    high_index = max(present, key=lambda index: (prepared.bars[index].high, -index))
    # Earliest bar that prints the extreme. max() with -index prefers the earliest tie.
    low_index = min(present, key=lambda index: (prepared.bars[index].low, index))
    high_bar = prepared.bars[high_index]
    low_bar = prepared.bars[low_index]
    last = prepared.bars[present[-1]]
    codes = {prepared.bars[index].contract_code for index in present}
    if len(codes) > 1:
        msg = "session level window crosses a contract roll"
        raise InsufficientDataError(msg)
    levels.append(
        SessionLevel(
            kind=kind,
            session_day=session_day,
            origin_time=window_open,
            confirmation_time=bar_close_time(last),
            timezone=timezone,
            high=high_bar.high,
            low=low_bar.low,
            high_time=high_bar.origin_time,
            low_time=low_bar.origin_time,
            contract_code=next(iter(codes)),
        )
    )


def _coverage(
    prepared: PreparedSeries,
    indexes: list[int],
    window_open: datetime,
    window_close: datetime,
    step: timedelta,
    *,
    is_first: bool,
    is_last: bool,
) -> str:
    expected = expected_origins(window_open, window_close, step)
    if not expected:
        return "empty"
    present = [
        prepared.bars[index].origin_time
        for index in indexes
        if window_open <= prepared.bars[index].origin_time < window_close
    ]
    if not present:
        return "empty"
    expected_set = set(expected)
    if any(origin not in expected_set for origin in present):
        msg = "bar inside a session window is not on the timeframe grid"
        raise InsufficientDataError(msg)
    start = expected.index(present[0])
    end = expected.index(present[-1])
    block = expected[start : end + 1]
    if block != present:
        msg = "missing bar inside a session window"
        raise InsufficientDataError(msg)
    _reject_bad_gaps(prepared, indexes, window_open, window_close)
    if start == 0 and end == len(expected) - 1:
        return "full"
    if start == 0 and end < len(expected) - 1 and is_last:
        return "prefix"
    if start > 0 and end == len(expected) - 1 and is_first:
        return "censored"
    msg = "missing bar inside a session window"
    raise InsufficientDataError(msg)


def _reject_bad_gaps(
    prepared: PreparedSeries,
    indexes: list[int],
    window_open: datetime,
    window_close: datetime,
) -> None:
    inside = [
        index for index in indexes if window_open <= prepared.bars[index].origin_time < window_close
    ]
    for left, right in itertools.pairwise(inside):
        if right != left + 1 or prepared.gaps[left] != "ok":
            msg = "missing bar or roll inside a session window"
            raise InsufficientDataError(msg)
