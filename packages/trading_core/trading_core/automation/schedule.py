"""Timezone-aware cron for research routines.

Five fields: minute hour day-of-month month day-of-week. Day-of-week uses 0 and 7 as
Sunday. When both day-of-month and day-of-week are restricted, a time matches if either
matches (standard cron). The returned instant is UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_FIELDS = 5
_MINUTES_AHEAD = 366 * 24 * 60


class ScheduleError(ValueError):
    pass


def next_occurrence(cron: str, timezone: str, after: datetime) -> datetime:
    """Next UTC instant strictly after ``after`` that matches ``cron`` in ``timezone``."""
    if after.tzinfo is None:
        msg = "schedule calculations require a timezone-aware instant"
        raise ScheduleError(msg)
    tz = _zone(timezone)
    fields = _parse(cron)
    local = after.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(_MINUTES_AHEAD):
        if _matches(fields, local):
            return local.astimezone(UTC)
        local += timedelta(minutes=1)
    msg = f"no occurrence of {cron!r} within a year"
    raise ScheduleError(msg)


def validate_cron(cron: str) -> str:
    _parse(cron)
    return cron


def validate_timezone(timezone: str) -> str:
    _zone(timezone)
    return timezone


def local_midnight(now: datetime, timezone: str) -> datetime:
    """UTC instant of midnight at the start of ``now``'s local day."""
    tz = _zone(timezone)
    local = now.astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC)


def _zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        msg = f"unknown timezone {timezone!r}"
        raise ScheduleError(msg) from exc


def _parse(cron: str) -> tuple[str, str, str, str, str]:
    parts = cron.split()
    if len(parts) != _FIELDS:
        msg = "cron must have five fields: minute hour day-of-month month day-of-week"
        raise ScheduleError(msg)
    minute, hour, dom, month, dow = parts
    _validate_field(minute, 0, 59)
    _validate_field(hour, 0, 23)
    _validate_field(dom, 1, 31)
    _validate_field(month, 1, 12)
    _validate_field(dow, 0, 7)
    return minute, hour, dom, month, dow


def _validate_field(field: str, low: int, high: int) -> None:
    if field == "*":
        return
    for part in field.split(","):
        step_value = _step(part)
        if step_value is not None:
            if step_value < 1:
                msg = f"invalid cron step {part!r}"
                raise ScheduleError(msg)
            continue
        start, end = _bounds(part)
        if start < low or end > high or start > end:
            msg = f"cron value {part!r} is outside {low}-{high}"
            raise ScheduleError(msg)


def _step(part: str) -> int | None:
    if not part.startswith("*/"):
        return None
    try:
        return int(part[2:])
    except ValueError as exc:
        msg = f"invalid cron step {part!r}"
        raise ScheduleError(msg) from exc


def _bounds(part: str) -> tuple[int, int]:
    piece = part
    if "-" in part:
        left, right = part.split("-", 1)
        piece = left
        try:
            return int(left), int(right)
        except ValueError as exc:
            msg = f"invalid cron range {part!r}"
            raise ScheduleError(msg) from exc
    try:
        value = int(piece)
    except ValueError as exc:
        msg = f"invalid cron value {part!r}"
        raise ScheduleError(msg) from exc
    return value, value


def _matches(fields: tuple[str, str, str, str, str], local: datetime) -> bool:
    minute, hour, dom, month, dow = fields
    if not _field_matches(minute, local.minute):
        return False
    if not _field_matches(hour, local.hour):
        return False
    if not _field_matches(month, local.month):
        return False
    dom_match = _field_matches(dom, local.day)
    dow_value = (local.weekday() + 1) % 7
    dow_match = _field_matches(dow, dow_value) or (dow_value == 0 and _field_matches(dow, 7))
    if dom != "*" and dow != "*":
        return dom_match or dow_match
    return dom_match and dow_match


def _field_matches(field: str, value: int) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        step = _step(part)
        if step is not None:
            if value % step == 0:
                return True
            continue
        start, end = _bounds(part)
        if start <= value <= end:
            return True
    return False
