"""Enumerate bar origin times from a :class:`SessionCalendar`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from trading_core.domain.instruments import SessionCalendar, Weekday

_WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def is_trading_day(calendar: SessionCalendar, day: date) -> bool:
    return _WEEKDAYS[day.weekday()] in calendar.trading_days and day not in calendar.holidays


def session_dates(calendar: SessionCalendar, start: date, count: int) -> list[date]:
    """The first ``count`` session dates on or after ``start``."""
    out: list[date] = []
    day = start
    while len(out) < count:
        if is_trading_day(calendar, day):
            out.append(day)
        day += timedelta(days=1)
    return out


def session_windows_utc(
    calendar: SessionCalendar, session_date: date
) -> list[tuple[datetime, datetime]]:
    """UTC [open, close) intervals of the bar-producing windows for one session date."""
    tz = ZoneInfo(calendar.timezone)
    windows: list[tuple[datetime, datetime]] = []
    for window in calendar.windows:
        if window.kind != "trading":
            continue
        open_day = session_date - timedelta(days=1) if window.opens_previous_day else session_date
        opens = datetime.combine(open_day, window.open_time, tzinfo=tz)
        closes = datetime.combine(session_date, window.close_time, tzinfo=tz)
        if closes <= opens:
            # Same clock time for open and close means a full 24-hour window.
            closes = datetime.combine(
                session_date + timedelta(days=1), window.close_time, tzinfo=tz
            )
        windows.append((opens.astimezone(UTC), closes.astimezone(UTC)))
    return windows


def bar_origins(
    calendar: SessionCalendar, start: date, session_count: int, bar_seconds: int
) -> list[tuple[date, datetime]]:
    """(session_date, origin_time_utc) for every bar across ``session_count`` sessions."""
    step = timedelta(seconds=bar_seconds)
    origins: list[tuple[date, datetime]] = []
    for session_date in session_dates(calendar, start, session_count):
        for opens, closes in session_windows_utc(calendar, session_date):
            cursor = opens
            while cursor + step <= closes:
                origins.append((session_date, cursor))
                cursor += step
    return origins
