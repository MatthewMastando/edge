"""When a confirmed TA event may create a research job.

Every confirmed event is already stored on ``ta_events``. This decision only gates the
research job: allowlist, cooldown, daily cap, and whether the market was open.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from trading_core.automation.schedule import ScheduleError, validate_timezone
from trading_core.fixtures.sessions import is_trading_day

if TYPE_CHECKING:
    from trading_core.domain.instruments import SessionCalendar

TriggerDecision = Literal["enqueued", "cooldown", "daily_cap", "allowlist", "closed_market"]

DEFAULT_COOLDOWN_SECONDS = 14_400
CRYPTO_CLASSES = frozenset({"crypto_spot", "crypto_futures"})


def trigger_decision(
    *,
    detector: str,
    allowlist: set[str],
    confirmation_time: datetime,
    last_enqueued_at: datetime | None,
    cooldown_seconds: int,
    enqueued_today: int,
    daily_cap: int,
    market_open: bool,
) -> TriggerDecision:
    """Return ``enqueued`` only when every routine rule passes."""
    if detector not in allowlist:
        return "allowlist"
    if not market_open:
        return "closed_market"
    if _in_cooldown(confirmation_time, last_enqueued_at, cooldown_seconds):
        return "cooldown"
    if enqueued_today >= daily_cap:
        return "daily_cap"
    return "enqueued"


def _in_cooldown(
    confirmation_time: datetime, last_enqueued_at: datetime | None, cooldown_seconds: int
) -> bool:
    if last_enqueued_at is None or cooldown_seconds <= 0:
        return False
    return confirmation_time - last_enqueued_at < timedelta(seconds=cooldown_seconds)


def market_is_open(
    calendar: SessionCalendar,
    when: datetime,
    *,
    asset_class: str,
    crypto_monitoring: str,
) -> bool:
    """Futures and equities follow the session calendar. Crypto can ignore it."""
    if asset_class in CRYPTO_CLASSES and crypto_monitoring != "calendar":
        return True
    if calendar.always_open:
        return True
    try:
        validate_timezone(calendar.timezone)
    except ScheduleError:
        return False
    local_day = when.astimezone(ZoneInfo(calendar.timezone)).date()
    return is_trading_day(calendar, local_day)
