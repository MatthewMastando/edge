"""Schedules, trigger gates, alerts and simulated P&L. No database."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from pydantic import JsonValue

from trading_core.automation.alerts import decide_alert
from trading_core.automation.hypotheses import PriceBar, apply_price_path
from trading_core.automation.pnl import simulated_pnl
from trading_core.automation.rules import market_is_open, trigger_decision
from trading_core.automation.schedule import ScheduleError, local_midnight, next_occurrence
from trading_core.domain.instruments import SessionCalendar

WEDNESDAY = datetime(2026, 9, 23, 13, 0, tzinfo=UTC)  # 09:00 America/New_York


def _calendar(*, always_open: bool = False, holidays: list[date] | None = None) -> SessionCalendar:
    return SessionCalendar(
        id="test",
        name="Test",
        version="1.0.0",
        timezone="America/New_York",
        trading_days=["mon", "tue", "wed", "thu", "fri"],
        windows=[],
        holidays=holidays or [],
        always_open=always_open,
    )


def test_weekday_cron_uses_the_routine_timezone() -> None:
    nxt = next_occurrence("30 8 * * 1-5", "America/New_York", after=WEDNESDAY)
    assert nxt == datetime(2026, 9, 24, 12, 30, tzinfo=UTC)
    friday = datetime(2026, 9, 25, 13, 0, tzinfo=UTC)
    monday = next_occurrence("30 8 * * 1-5", "America/New_York", after=friday)
    assert monday == datetime(2026, 9, 28, 12, 30, tzinfo=UTC)


def test_sunday_zero_and_seven_match_and_steps_advance() -> None:
    saturday = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)
    assert next_occurrence("0 0 * * 0", "UTC", after=saturday) == datetime(
        2026, 9, 27, 0, 0, tzinfo=UTC
    )
    assert next_occurrence("0 0 * * 7", "UTC", after=saturday) == datetime(
        2026, 9, 27, 0, 0, tzinfo=UTC
    )
    after = datetime(2026, 9, 23, 10, 7, tzinfo=UTC)
    assert next_occurrence("*/15 * * * *", "UTC", after=after) == datetime(
        2026, 9, 23, 10, 15, tzinfo=UTC
    )


def test_day_of_month_or_weekday_and_local_midnight() -> None:
    # 1 September 2026 is a Tuesday. Monday the 7th also matches because both fields are set.
    after = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    assert next_occurrence("0 12 1 * 1", "UTC", after=after) == datetime(
        2026, 9, 7, 12, 0, tzinfo=UTC
    )
    late = datetime(2026, 9, 23, 3, 0, tzinfo=UTC)  # 23:00 the previous evening in New York
    assert local_midnight(late, "America/New_York") == datetime(2026, 9, 22, 4, 0, tzinfo=UTC)


def test_schedule_rejects_naive_instants_and_bad_expressions() -> None:
    with pytest.raises(ScheduleError):
        next_occurrence("* * * * *", "UTC", after=datetime(2026, 9, 23, 0, 0))
    with pytest.raises(ScheduleError):
        next_occurrence("* * * *", "UTC", after=WEDNESDAY)
    with pytest.raises(ScheduleError):
        next_occurrence("0 8 * * *", "Not/AZone", after=WEDNESDAY)


def test_trigger_rules_are_ordered_and_default_cooldown_is_four_hours() -> None:
    now = WEDNESDAY
    allow = {"fvg"}
    assert (
        trigger_decision(
            detector="bos",
            allowlist=allow,
            confirmation_time=now,
            last_enqueued_at=None,
            cooldown_seconds=14_400,
            enqueued_today=0,
            daily_cap=6,
            market_open=True,
        )
        == "allowlist"
    )
    assert (
        trigger_decision(
            detector="fvg",
            allowlist=allow,
            confirmation_time=now,
            last_enqueued_at=None,
            cooldown_seconds=14_400,
            enqueued_today=0,
            daily_cap=6,
            market_open=False,
        )
        == "closed_market"
    )
    assert (
        trigger_decision(
            detector="fvg",
            allowlist=allow,
            confirmation_time=now,
            last_enqueued_at=now - timedelta(hours=3, minutes=59),
            cooldown_seconds=14_400,
            enqueued_today=0,
            daily_cap=6,
            market_open=True,
        )
        == "cooldown"
    )
    assert (
        trigger_decision(
            detector="fvg",
            allowlist=allow,
            confirmation_time=now,
            last_enqueued_at=now - timedelta(hours=4),
            cooldown_seconds=14_400,
            enqueued_today=6,
            daily_cap=6,
            market_open=True,
        )
        == "daily_cap"
    )
    assert (
        trigger_decision(
            detector="fvg",
            allowlist=allow,
            confirmation_time=now,
            last_enqueued_at=now - timedelta(hours=4),
            cooldown_seconds=14_400,
            enqueued_today=5,
            daily_cap=6,
            market_open=True,
        )
        == "enqueued"
    )


def test_crypto_ignores_the_equity_calendar_unless_asked() -> None:
    holiday = _calendar(holidays=[date(2026, 9, 23)])
    when = WEDNESDAY
    assert market_is_open(holiday, when, asset_class="crypto_spot", crypto_monitoring="always")
    assert not market_is_open(
        holiday, when, asset_class="crypto_futures", crypto_monitoring="calendar"
    )
    assert not market_is_open(holiday, when, asset_class="futures", crypto_monitoring="always")
    assert market_is_open(
        _calendar(always_open=True), when, asset_class="futures", crypto_monitoring="always"
    )
    open_day = _calendar()
    assert market_is_open(open_day, when, asset_class="equity", crypto_monitoring="always")
    assert not market_is_open(
        open_day,
        datetime(2026, 9, 26, 15, 0, tzinfo=UTC),
        asset_class="equity",
        crypto_monitoring="always",
    )


def test_alerts_skip_unchanged_insufficient_research() -> None:
    insufficient = cast(
        "dict[str, JsonValue]",
        {"stance": "insufficient_evidence", "plan": {"entry": None}},
    )
    assert decide_alert(insufficient, None) is None
    actionable = cast(
        "dict[str, JsonValue]",
        {
            "stance": "bullish",
            "plan": {"entry": "1.10", "invalidation": "1.00", "target": "1.20"},
        },
    )
    assert decide_alert(actionable, None) == "new_research"
    changed = cast(
        "dict[str, JsonValue]",
        {
            "stance": "bullish",
            "plan": {"entry": "1.11", "invalidation": "1.00", "target": "1.20"},
        },
    )
    assert decide_alert(changed, actionable) == "material_change"
    assert decide_alert(actionable, actionable) == "new_research"
    assert decide_alert(insufficient, actionable) == "material_change"


def test_simulated_pnl_is_signed_and_net_of_cost() -> None:
    assert simulated_pnl(
        stance="bullish",
        entry=Decimal("100"),
        exit_price=Decimal("110"),
        multiplier=Decimal("10"),
        cost=Decimal("1"),
    ) == Decimal("99")
    assert simulated_pnl(
        stance="bearish",
        entry=Decimal("100"),
        exit_price=Decimal("90"),
        multiplier=Decimal("10"),
        cost=Decimal("1"),
    ) == Decimal("99")
    assert simulated_pnl(
        stance="neutral",
        entry=Decimal("100"),
        exit_price=Decimal("110"),
        multiplier=Decimal("10"),
        cost=Decimal("1"),
    ) == Decimal(0)


def _bar(at: datetime, *, low: str, high: str, close: str) -> PriceBar:
    return PriceBar(
        origin_time=at,
        origin_tz="America/New_York",
        low=Decimal(low),
        high=Decimal(high),
        close=Decimal(close),
    )


def test_price_path_freezes_entry_invalidation_and_simulated_exit() -> None:
    start = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
    bars = [
        _bar(start - timedelta(minutes=5), low="9", high="11", close="10"),
        _bar(start, low="9", high="11", close="10"),
        _bar(start + timedelta(minutes=5), low="7", high="9", close="8"),
    ]
    path = apply_price_path(
        stance="bullish",
        entry=Decimal("10"),
        invalidation=Decimal("9"),
        target=Decimal("20"),
        frozen_at=start,
        status="open",
        entry_state="untriggered",
        bars=bars,
        multiplier=Decimal("2"),
        cost=Decimal("1"),
        data_revision="rev",
    )
    assert path.entry_state == "triggered"
    assert path.status == "invalidated"
    assert path.subsequent_move == Decimal("-2")
    assert path.simulated_pnl == Decimal("-3")
    assert path.exit_kind == "invalidation"
    events = [item[0] for item in path.observations]
    assert events == ["entry_triggered", "invalidation_hit", "checkpoint"]


def test_untriggered_path_has_no_simulated_pnl() -> None:
    start = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
    bars = [
        _bar(start, low="9", high="11", close="10"),
        _bar(start + timedelta(minutes=5), low="12", high="14", close="13"),
    ]
    path = apply_price_path(
        stance="bullish",
        entry=Decimal("100"),
        invalidation=Decimal("1"),
        target=Decimal("200"),
        frozen_at=start,
        status="open",
        entry_state="untriggered",
        bars=bars,
        multiplier=Decimal("1"),
        cost=Decimal("0"),
        data_revision="rev",
    )
    assert path.entry_state == "untriggered"
    assert path.status == "open"
    assert path.simulated_pnl is None
    assert path.subsequent_move == Decimal("3")


def test_bearish_target_uses_the_low() -> None:
    start = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
    path = apply_price_path(
        stance="bearish",
        entry=Decimal("10"),
        invalidation=Decimal("20"),
        target=Decimal("8"),
        frozen_at=start,
        status="open",
        entry_state="untriggered",
        bars=[_bar(start, low="8", high="10", close="9")],
        multiplier=Decimal("2"),
        cost=Decimal("0"),
        data_revision="rev",
    )
    assert path.status == "target_hit"
    assert path.simulated_pnl == Decimal("4")
    assert path.exit_kind == "target"
