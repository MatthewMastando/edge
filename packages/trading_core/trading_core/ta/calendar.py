"""Session windows for TA.

Holiday handling reads ``SessionCalendar.holidays`` only. An empty list means the weekday is
open: this module does not consult ``exchange_calendars`` and will not close Labor Day on its own.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from trading_core.fixtures.sessions import is_trading_day, session_windows_utc

if TYPE_CHECKING:
    from trading_core.domain.instruments import SessionCalendar, SessionWindow


def _window_bounds(
    calendar: SessionCalendar, session_date: date, window: SessionWindow
) -> tuple[datetime, datetime]:
    tz = ZoneInfo(calendar.timezone)
    open_day = session_date - timedelta(days=1) if window.opens_previous_day else session_date
    opens = datetime.combine(open_day, window.open_time, tzinfo=tz).astimezone(UTC)
    closes = datetime.combine(session_date, window.close_time, tzinfo=tz).astimezone(UTC)
    if closes <= opens:
        closes = datetime.combine(
            session_date + timedelta(days=1), window.close_time, tzinfo=tz
        ).astimezone(UTC)
    return opens, closes


def subsession_windows(
    calendar: SessionCalendar, session_date: date, *, name: str | None = None
) -> list[tuple[str, datetime, datetime]]:
    """``(name, open, close)`` for ``sub_session`` windows. ``[open, close)`` in UTC."""
    found: list[tuple[str, datetime, datetime]] = []
    for window in calendar.windows:
        if window.kind != "sub_session":
            continue
        if name is not None and window.name != name:
            continue
        opens, closes = _window_bounds(calendar, session_date, window)
        found.append((window.name, opens, closes))
    return found


def rth_bounds(calendar: SessionCalendar, session_date: date) -> tuple[datetime, datetime] | None:
    """Separate RTH sub-window, if the calendar defines one.

    A trading window that is itself named ``rth`` (equities) is the whole session, not a
    separate overnight split, and returns ``None``.
    """
    named = subsession_windows(calendar, session_date, name="rth")
    if named:
        _, opens, closes = named[0]
        return opens, closes
    any_sub = subsession_windows(calendar, session_date)
    if any_sub:
        _, opens, closes = any_sub[0]
        return opens, closes
    return None


def trading_bounds(
    calendar: SessionCalendar, session_date: date
) -> list[tuple[datetime, datetime]]:
    if not is_trading_day(calendar, session_date):
        return []
    return session_windows_utc(calendar, session_date)


def locate_session(
    calendar: SessionCalendar, instant: datetime
) -> tuple[date, datetime, datetime] | None:
    """Return ``(session_date, trading_open, trading_close)`` containing ``instant``.

    ``instant`` is matched against ``[open, close)``. Dates a couple of days either side are
    checked so a Globex bar that opens the previous evening still resolves.
    """
    local_day = instant.astimezone(ZoneInfo(calendar.timezone)).date()
    found: list[tuple[date, datetime, datetime]] = []
    for delta in (-1, 0, 1, 2):
        session_date = local_day + timedelta(days=delta)
        for opens, closes in trading_bounds(calendar, session_date):
            if opens <= instant < closes:
                found.append((session_date, opens, closes))
    if not found:
        return None
    if len(found) > 1:
        msg = f"session windows overlap at {instant.isoformat()}"
        raise ValueError(msg)
    return found[0]


def next_trading_open(calendar: SessionCalendar, at_or_after: datetime) -> datetime | None:
    """First trading-window open at or after ``at_or_after``."""
    local_day = at_or_after.astimezone(ZoneInfo(calendar.timezone)).date()
    candidates: list[datetime] = []
    for delta in range(-1, 21):
        session_date = local_day + timedelta(days=delta)
        for opens, _closes in trading_bounds(calendar, session_date):
            if opens >= at_or_after:
                candidates.append(opens)
    if not candidates:
        return None
    return min(candidates)


def expected_origins(open_time: datetime, close_time: datetime, step: timedelta) -> list[datetime]:
    origins: list[datetime] = []
    cursor = open_time
    while cursor + step <= close_time:
        origins.append(cursor)
        cursor += step
    return origins
