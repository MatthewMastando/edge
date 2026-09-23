"""Pivots, pools, session levels, VWAP, correlation, gaps, rolls, and Labor Day."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from tests.conftest import FIXTURES_DIR
from tests.unit.ta.helpers import (
    crypto_calendar,
    detector_input,
    make_bars,
    make_trades,
    ohlc,
    other_rows,
    short_session_calendar,
    split_calendar,
    utc,
    weekday_calendar,
)

from trading_core.fixtures.sessions import bar_origins
from trading_core.fixtures.spec import load_fixture_inputs
from trading_core.ta import CALC_VERSION, incremental_replay, replay_violations
from trading_core.ta.detectors.fvg import FvgDetector
from trading_core.ta.detectors.supporting import (
    AtrDetector,
    CorrelationDetector,
    LiquidityPoolDetector,
    SessionLevelsDetector,
    SwingPivotDetector,
    VwapDetector,
)
from trading_core.ta.envelope import event_identity
from trading_core.ta.interfaces import InsufficientDataError


def test_strict_pivot_confirms_three_bars_later_and_equals_are_pools() -> None:
    highs = [10, 20, 30, 50, 70, 80, 50, 90, 100, 110]
    candles = [ohlc(high, high=high, low=1) for high in highs]
    bars = make_bars(candles, start=utc(2026, 9, 7))
    pivots = SwingPivotDetector().run(detector_input(bars, crypto_calendar()))
    assert pivots.events == []
    pools = LiquidityPoolDetector().run(detector_input(bars, crypto_calendar()))
    equal_highs = [event for event in pools.events if event.levels[0].name == "equal_high"]
    assert len(equal_highs) == 1
    assert equal_highs[0].levels[0].price == Decimal(50)
    assert equal_highs[0].details["members"] == [3, 6]
    assert equal_highs[0].event_time == bars[6].origin_time + timedelta(minutes=15)


def test_unique_swing_is_known_only_at_i_plus_3() -> None:
    highs = [5, 6, 7, 12, 7, 6, 5, 5]
    candles = [ohlc(4, high=high, low=1) for high in highs]
    bars = make_bars(candles, start=utc(2026, 9, 7))
    detector = SwingPivotDetector()
    steps = incremental_replay(detector, detector_input(bars, crypto_calendar()))
    assert replay_violations(steps) == []
    early = [step for step in steps if step.as_of < bars[6].origin_time + timedelta(minutes=15)]
    assert all(step.events == () for step in early)
    confirmed = next(step for step in steps if step.events)
    assert confirmed.events[0].origin_time == bars[3].origin_time
    assert confirmed.events[0].event_time == bars[6].origin_time + timedelta(minutes=15)
    assert confirmed.events[0].calc_version == CALC_VERSION
    full = detector.run(detector_input(bars, crypto_calendar()))
    assert full.events[0].model_dump_json() == confirmed.events[0].model_dump_json()
    again = detector.run(detector_input(bars, crypto_calendar()))
    assert again.events[0].id == full.events[0].id


def test_flat_prices_have_no_pivots() -> None:
    bars = make_bars([ohlc(10)] * 10, start=utc(2026, 9, 7))
    assert SwingPivotDetector().run(detector_input(bars, crypto_calendar())).events == []
    pools = LiquidityPoolDetector().run(detector_input(bars, crypto_calendar()))
    names = sorted(event.levels[0].name for event in pools.events)
    assert names == ["equal_high", "equal_low"]


def test_session_levels_and_vwap() -> None:
    start = utc(2026, 9, 7, 8)
    candles = [
        ohlc(10, high=12, low=9),
        ohlc(11, high=12, low=8),
        ohlc(15, high=18, low=14),
        ohlc(16, high=17, low=13),
    ]
    bars = make_bars(candles, start=start, timeframe="1h")
    levels = SessionLevelsDetector().run(detector_input(bars, split_calendar()))
    by_session = {feature.session: feature for feature in levels.features}
    assert set(by_session) == {"rth", "overnight"}
    overnight = by_session["overnight"]
    rth = by_session["rth"]
    assert {level.name: level.price for level in overnight.levels} == {
        "onh": Decimal(12),
        "onl": Decimal(8),
    }
    assert {level.name: level.price for level in rth.levels} == {
        "pdh": Decimal(18),
        "pdl": Decimal(14),
    }
    assert overnight.origin_time == utc(2026, 9, 7, 8)
    assert rth.origin_time == utc(2026, 9, 7, 10)
    assert "overnight levels are unavailable" not in " ".join(levels.warnings)

    crypto = SessionLevelsDetector().run(
        detector_input(make_bars([ohlc(1)] * 4, start=utc(2026, 9, 7)), crypto_calendar())
    )
    assert crypto.features == []
    assert any("overnight" in warning for warning in crypto.warnings)

    vwap = VwapDetector().run(detector_input(bars[:2], split_calendar()))
    # typical prices: (12+9+10)/3 = 31/3, (12+8+11)/3 = 31/3. Equal bars keep that value.
    assert vwap.features[0].details["source"] == "bar_typical"
    assert vwap.features[0].details["value"] == format(Decimal(31) / Decimal(3), "f")


def test_trade_vwap_and_session_reset() -> None:
    start = utc(2026, 9, 7, 11)
    nxt = utc(2026, 9, 8, 8)
    bars = make_bars(
        [ohlc(10), ohlc(10)],
        start=start,
        timeframe="1h",
        volume="0",
        origins=[start, nxt],
    )
    trades = make_trades(
        [
            (start + timedelta(minutes=1), "10", "2"),
            (start + timedelta(minutes=2), "20", "2"),
            (nxt + timedelta(minutes=1), "5", "1"),
        ]
    )
    output = VwapDetector().run(detector_input(bars, split_calendar(), trades=trades))
    assert output.features[0].details["value"] == "15"
    assert output.features[0].details["source"] == "trades"
    assert output.features[1].details["value"] == "5"


def test_correlation_of_aligned_returns() -> None:
    closes = [Decimal(10), Decimal(11), Decimal(12), Decimal(13)]
    bars = make_bars([ohlc(format(close, "f")) for close in closes], start=utc(2026, 9, 7))
    output = CorrelationDetector().run(
        detector_input(
            bars,
            crypto_calendar(),
            parameters={"other_bars": other_rows(bars), "other_instrument_id": "other-1"},
        )
    )
    assert output.features[0].details["correlation"] == "1"
    assert output.features[0].details["n"] == 3
    assert output.features[0].details["method"] == "sample_pearson"
    flat = make_bars([ohlc(10)] * 6, start=utc(2026, 9, 7))
    with pytest.raises(InsufficientDataError, match="flat"):
        CorrelationDetector().run(
            detector_input(
                flat,
                crypto_calendar(),
                parameters={"other_bars": other_rows(flat), "other_instrument_id": "other-1"},
            )
        )


def test_fvg_skips_session_gaps_missing_bars_and_rolls() -> None:
    calendar = short_session_calendar()
    day1 = [utc(2026, 9, 7, 9, minute) for minute in (0, 15, 30, 45)]
    day2 = [utc(2026, 9, 8, 9, 0)]
    gap_candles = [
        ohlc(9, high=10, low=8),
        ohlc(14, high=14, low=12, open_=12),
        ohlc(17, high=17, low=16, open_=16),
        ohlc(14, high=15, low=14),
        ohlc(20, high=20, low=19, open_=19),
    ]
    bars = make_bars(gap_candles, start=day1[0], origins=day1 + day2)
    output = FvgDetector().run(detector_input(bars, calendar))
    assert len(output.events) == 1
    assert output.events[0].origin_time == day1[1]
    assert output.events[0].direction == "bullish"
    assert "not one timeframe apart" in " ".join(output.warnings)

    missing_origins = [day1[0], day1[1], day1[3]]
    missing = make_bars(
        [ohlc(9, high=10, low=8), ohlc(14, high=14, low=12), ohlc(17, high=17, low=16)],
        start=day1[0],
        origins=missing_origins,
    )
    with pytest.raises(InsufficientDataError, match="missing bar"):
        AtrDetector().run(detector_input(missing, calendar))
    skipped = FvgDetector().run(detector_input(missing, calendar))
    assert skipped.events == []

    rolled = make_bars(
        gap_candles[:3],
        start=day1[0],
        origins=day1[:3],
        contracts=["ESU6", "ESU6", "ESZ6"],
    )
    rolled_out = FvgDetector().run(
        detector_input(
            rolled,
            calendar,
            parameters={"roll_times": [day1[2].isoformat()]},
        )
    )
    assert rolled_out.events == []


def test_weekend_does_not_reset_atr_and_labor_day_stays_open() -> None:
    calendar = weekday_calendar()
    assert date(2026, 9, 7) not in calendar.holidays
    origins = [instant for _, instant in bar_origins(calendar, date(2026, 8, 31), 8, 900)]
    assert len(origins) == 16
    assert any(instant.date() == date(2026, 9, 7) for instant in origins)
    candles = [ohlc(100 + index) for index in range(16)]
    bars = make_bars(candles, start=origins[0], origins=origins)
    output = AtrDetector().run(detector_input(bars, calendar))
    assert "session" not in output.warnings[0] if output.warnings else True
    assert output.features[0].details["value"] == "1"
    assert not any("roll" in warning for warning in output.warnings)

    equity = load_fixture_inputs(FIXTURES_DIR).calendar_for("us_equity_rth")
    assert equity.holidays == []
    labor = make_bars([ohlc("100")], start=utc(2026, 9, 7, 13, 30))
    with pytest.raises(InsufficientDataError, match="warm-up") as caught:
        AtrDetector().run(detector_input(labor, equity))
    assert "outside the session calendar" not in str(caught.value)


def test_atr_restarts_on_a_roll_and_not_on_a_session_break() -> None:
    candles = []
    contracts: list[str | None] = []
    for index in range(30):
        base = 100 if index < 15 else 400
        close = base + (index % 15)
        width = 1 if index < 15 else 2
        candles.append(ohlc(close, high=close + width, low=close - width))
        contracts.append("ESU6" if index < 15 else "ESZ6")
    bars = make_bars(candles, start=utc(2026, 9, 7), contracts=contracts)
    output = AtrDetector().run(detector_input(bars, crypto_calendar()))
    assert [feature.details["value"] for feature in output.features] == ["2", "4"]
    assert any("roll" in warning for warning in output.warnings)


def test_contract_code_keeps_event_keys_distinct() -> None:
    candles = [ohlc(4, high=high, low=1) for high in (5, 6, 7, 12, 7, 6, 5)]
    start = utc(2026, 9, 7)
    first = SwingPivotDetector().run(
        detector_input(make_bars(candles, start=start, contract="ESU6"), crypto_calendar())
    )
    second = SwingPivotDetector().run(
        detector_input(make_bars(candles, start=start, contract="ESZ6"), crypto_calendar())
    )
    assert event_identity(first.events[0]) != event_identity(second.events[0])
    assert first.events[0].contract_code == "ESU6"
    assert second.events[0].contract_code == "ESZ6"
