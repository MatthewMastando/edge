"""Sweeps, breaks, order blocks, divergence, and no-lookahead replay."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import JsonValue
from tests.unit.ta.helpers import (
    INSTRUMENT_ID,
    REVISION,
    SNAPSHOT_ID,
    crypto_calendar,
    detector_input,
    make_bars,
    ohlc,
    utc,
)

from trading_core.domain.market import Bar
from trading_core.domain.ta import DetectorName
from trading_core.ta import CALC_VERSION, ReplayStep, incremental_replay, replay_violations
from trading_core.ta.detectors import default_registry
from trading_core.ta.detectors.bos import BosDetector
from trading_core.ta.detectors.fvg import FvgDetector
from trading_core.ta.detectors.liquidity_sweep import LiquiditySweepDetector
from trading_core.ta.detectors.order_block import OrderBlockDetector
from trading_core.ta.detectors.rsi_divergence import RsiDivergenceDetector
from trading_core.ta.detectors.supporting import SwingPivotDetector
from trading_core.ta.divergence import find_divergences
from trading_core.ta.series import prepare
from trading_core.ta.swings import Swing


def test_sweep_needs_a_close_back_through_a_known_level() -> None:
    highs = [5, 6, 7, 12, 7, 6, 5, 14, 5]
    closes = [4, 4, 4, 4, 4, 4, 4, 11, 4]
    lows = [1, 1, 1, 1, 1, 1, 1, 10, 1]
    candles = [
        ohlc(close, high=high, low=low)
        for close, high, low in zip(closes, highs, lows, strict=True)
    ]
    bars = make_bars(candles, start=utc(2026, 9, 7))
    output = LiquiditySweepDetector().run(detector_input(bars, crypto_calendar()))
    assert len(output.events) == 1
    assert output.events[0].origin_time == bars[7].origin_time
    assert output.events[0].direction == "bearish"
    hits = output.events[0].details["hits"]
    assert isinstance(hits, list)
    first = hits[0]
    assert isinstance(first, dict)
    assert first["source"] == "swing_high"
    assert first["price"] == "12"

    wick_highs = highs.copy()
    wick_closes = closes.copy()
    wick_highs[7] = 14
    wick_closes[7] = 13
    wick = [
        ohlc(close, high=high, low=1) for close, high in zip(wick_closes, wick_highs, strict=True)
    ]
    quiet = LiquiditySweepDetector().run(
        detector_input(make_bars(wick, start=utc(2026, 9, 7)), crypto_calendar())
    )
    assert quiet.events == []


def test_bos_closes_beyond_the_latest_swing() -> None:
    highs = [5, 6, 7, 12, 7, 6, 5, 5, 5, 13]
    closes = [4, 4, 4, 4, 4, 4, 4, 4, 4, 13]
    candles = [
        ohlc(close, high=max(close, high), low=1) for close, high in zip(closes, highs, strict=True)
    ]
    bars = make_bars(candles, start=utc(2026, 9, 7))
    output = BosDetector().run(detector_input(bars, crypto_calendar()))
    assert len(output.events) == 1
    assert output.events[0].direction == "bullish"
    assert output.events[0].levels[0].name == "broken_level"
    assert output.events[0].levels[0].price == Decimal(12)
    assert output.events[0].details["kind"] == "unknown"
    assert output.events[0].origin_time == bars[9].origin_time


def test_order_block_uses_the_latest_opposite_candle() -> None:
    candles = []
    for index in range(24):
        if index == 10:
            candles.append(ohlc(9, high=20, low=8))
        elif index == 15:
            candles.append(ohlc(9, high=12, low=8, open_=12))
        elif index == 16:
            candles.append(ohlc(30, high=30, low=12, open_=12))
        else:
            candles.append(ohlc(9, high=10, low=8))
    bars = make_bars(candles, start=utc(2026, 9, 7))
    output = OrderBlockDetector().run(detector_input(bars, crypto_calendar()))
    assert output.events
    block = output.events[0]
    assert block.direction == "bullish"
    assert block.origin_time == bars[15].origin_time
    assert block.details["invalidation"] == "8"
    assert block.details["use_body"] is False
    names = {level.name: level.price for level in block.levels}
    assert names["zone_lower"] == Decimal(8)
    assert names["zone_upper"] == Decimal(12)


def test_fvg_fill_does_not_rewrite_the_confirmed_event() -> None:
    candles = [
        ohlc(9, high=10, low=8),
        ohlc(14, high=14, low=12, open_=12),
        ohlc(17, high=17, low=16, open_=16),
        ohlc(14, high=16, low=12),
        ohlc(9, high=12, low=8),
    ]
    bars = make_bars(candles, start=utc(2026, 9, 7))
    detector = FvgDetector()
    data = detector_input(bars, crypto_calendar())
    steps = incremental_replay(detector, data)
    assert replay_violations(steps) == []
    full = detector.run(data)
    assert full.events[0].details["fill_depth"] == "0"
    assert full.features[0].details["fill_depth"] == "1"
    assert full.features[0].state == "invalidated"
    assert full.events[0].model_dump_json() == steps[2].events[0].model_dump_json()
    assert any(item.to_state == "invalidated" for item in full.transitions)


def test_regular_divergence_and_hidden_flag() -> None:
    closes = [Decimal(50) - Decimal(index) for index in range(15)]
    closes.extend(Decimal(36) + Decimal(index) for index in range(1, 10))
    lows = [12] * len(closes)
    lows[14] = 10
    lows[20] = 8
    candles = [
        ohlc(format(close, "f"), low=low, high=format(close, "f"))
        for close, low in zip(closes, lows, strict=True)
    ]
    bars = make_bars(candles, start=utc(2026, 9, 7))
    output = RsiDivergenceDetector().run(detector_input(bars, crypto_calendar()))
    assert output.events
    assert output.events[0].direction == "bullish"
    assert output.events[0].details["kind"] == "regular"
    assert output.events[0].origin_time == bars[20].origin_time
    hidden = RsiDivergenceDetector()
    assert hidden.default_parameters()["include_hidden"] is False


def test_hidden_divergence_is_optional() -> None:
    candles = [ohlc(20, low=15)] * 12
    candles[3] = ohlc(20, low=10)
    candles[8] = ohlc(20, low=12)
    bars = make_bars(candles, start=utc(2026, 9, 7))
    prepared = prepare(detector_input(bars, crypto_calendar()), [])
    swings = [
        Swing(
            index=3,
            is_high=False,
            is_low=True,
            origin_time=bars[3].origin_time,
            origin_tz="UTC",
            confirmation_time=bars[6].origin_time + timedelta(minutes=15),
            confirmation_index=6,
            contract_code="ESZ6",
        ),
        Swing(
            index=8,
            is_high=False,
            is_low=True,
            origin_time=bars[8].origin_time,
            origin_tz="UTC",
            confirmation_time=bars[11].origin_time + timedelta(minutes=15),
            confirmation_index=11,
            contract_code="ESZ6",
        ),
    ]
    rsi = {3: Decimal(40), 8: Decimal(30)}
    hidden_off = find_divergences(
        prepared,
        swings,
        rsi,
        min_separation=5,
        max_separation=60,
        min_points=Decimal(2),
        include_hidden=False,
    )
    hidden_on = find_divergences(
        prepared,
        swings,
        rsi,
        min_separation=5,
        max_separation=60,
        min_points=Decimal(2),
        include_hidden=True,
    )
    assert hidden_off == []
    assert len(hidden_on) == 1
    assert hidden_on[0].kind == "hidden"
    assert hidden_on[0].direction == "bullish"

    regular = find_divergences(
        prepared,
        swings,
        {3: Decimal(30), 8: Decimal(40)},
        include_hidden=False,
        min_separation=5,
        max_separation=60,
        min_points=Decimal(2),
    )
    # Second low is higher, so a higher RSI is not regular bullish divergence.
    assert regular == []
    lower_low = make_bars(
        [ohlc(20, low=10 if index == 8 else 15 if index != 3 else 12) for index in range(12)],
        start=utc(2026, 9, 7),
    )
    prepared_regular = prepare(detector_input(lower_low, crypto_calendar()), [])
    found = find_divergences(
        prepared_regular,
        swings,
        {3: Decimal(30), 8: Decimal(40)},
        include_hidden=False,
        min_separation=5,
        max_separation=60,
        min_points=Decimal(2),
    )
    assert len(found) == 1
    assert found[0].kind == "regular"
    assert found[0].direction == "bullish"


def _default_candle() -> tuple[Decimal, Decimal, Decimal, Decimal]:
    return ohlc(12, high=15, low=10)


def _structure_bars(
    overrides: dict[int, tuple[Decimal, Decimal, Decimal, Decimal]],
    *,
    length: int = 22,
) -> list[Bar]:
    candles = [_default_candle() for _ in range(length)]
    candles[3] = ohlc(12, high=30, low=10)
    candles[7] = ohlc(12, high=15, low=2)
    candles[11] = ohlc(12, high=40, low=10)
    candles[15] = ohlc(12, high=15, low=5)
    for index, candle in overrides.items():
        candles[index] = candle
    return make_bars(candles, start=utc(2026, 9, 7))


def test_bos_continuation_and_structure_change() -> None:
    bars = _structure_bars(
        {
            19: ohlc(41, high=41, low=10),
            20: ohlc(1, high=12, low=1),
        }
    )
    output = BosDetector().run(detector_input(bars, crypto_calendar()))
    assert [(event.direction, event.details["kind"]) for event in output.events] == [
        ("bullish", "continuation"),
        ("bearish", "structure_change"),
    ]
    assert output.events[0].levels[0].price == Decimal(40)
    assert output.events[1].levels[0].price == Decimal(5)
    assert output.events[0].origin_time == bars[19].origin_time
    assert output.events[1].origin_time == bars[20].origin_time
    assert (
        replay_violations(
            incremental_replay(BosDetector(), detector_input(bars, crypto_calendar()))
        )
        == []
    )


def test_bos_rejects_wicks_and_closes_that_only_touch_the_level() -> None:
    wick = _structure_bars({19: ohlc(20, high=50, low=10)}, length=20)
    assert BosDetector().run(detector_input(wick, crypto_calendar())).events == []
    touch = _structure_bars({19: ohlc(40, high=40, low=10)}, length=20)
    assert BosDetector().run(detector_input(touch, crypto_calendar())).events == []
    through = _structure_bars({19: ohlc(41, high=41, low=10)}, length=20)
    broken = BosDetector().run(detector_input(through, crypto_calendar()))
    assert len(broken.events) == 1
    assert broken.events[0].levels[0].price == Decimal(40)


def test_sweep_close_at_the_level_is_not_a_reclaim_and_the_first_sweep_consumes_it() -> None:
    highs = [5, 6, 7, 12, 7, 6, 5, 14, 14]
    closes = [4, 4, 4, 4, 4, 4, 4, 12, 12]
    candles = [ohlc(close, high=high, low=1) for close, high in zip(closes, highs, strict=True)]
    quiet = LiquiditySweepDetector().run(
        detector_input(make_bars(candles, start=utc(2026, 9, 7)), crypto_calendar())
    )
    assert quiet.events == []
    closes[7] = 11
    closes[8] = 11
    swept = [ohlc(close, high=high, low=1) for close, high in zip(closes, highs, strict=True)]
    output = LiquiditySweepDetector().run(
        detector_input(make_bars(swept, start=utc(2026, 9, 7)), crypto_calendar())
    )
    assert len(output.events) == 1
    assert output.events[0].origin_time == utc(2026, 9, 7) + timedelta(minutes=15 * 7)


def test_fvg_one_tick_boundary_and_displacement_tag() -> None:
    gap = [
        ohlc(10, high=10, low=9),
        ohlc(11, high=12, low=10),
        ohlc(12, high=12, low=11),
    ]
    formed = FvgDetector().run(
        detector_input(make_bars(gap, start=utc(2026, 9, 7)), crypto_calendar())
    )
    assert len(formed.events) == 1
    assert formed.events[0].details["lower"] == "10"
    assert formed.events[0].details["upper"] == "11"
    assert formed.events[0].details["displacement"] is None
    touch = [
        ohlc(10, high=10, low=9),
        ohlc(11, high=12, low=10),
        ohlc(12, high=12, low=10),
    ]
    assert (
        FvgDetector()
        .run(detector_input(make_bars(touch, start=utc(2026, 9, 7)), crypto_calendar()))
        .events
        == []
    )

    flat = [ohlc(100, high=101, low=100)] * 15
    displaced = [
        *flat,
        ohlc(110, high=110, low=100, open_=100),
        ohlc(114, high=114, low=112, open_=112),
    ]
    quiet_body = [
        *flat,
        ohlc(100, high=110, low=100, open_=100),
        ohlc(114, high=114, low=112, open_=112),
    ]
    yes = FvgDetector().run(
        detector_input(make_bars(displaced, start=utc(2026, 9, 7)), crypto_calendar())
    )
    no = FvgDetector().run(
        detector_input(make_bars(quiet_body, start=utc(2026, 9, 7)), crypto_calendar())
    )
    assert yes.events[0].details["displacement"] is True
    assert no.events[0].details["displacement"] is False


def _order_block_candles() -> list[tuple[Decimal, Decimal, Decimal, Decimal]]:
    candles = []
    for index in range(24):
        if index == 10:
            candles.append(ohlc(9, high=20, low=8))
        elif index == 15:
            candles.append(ohlc(9, high=12, low=8, open_=12))
        elif index == 16:
            candles.append(ohlc(30, high=30, low=12, open_=12))
        else:
            candles.append(ohlc(9, high=10, low=8))
    return candles


def test_order_block_traversal_does_not_rewrite_the_event() -> None:
    candles = _order_block_candles()
    candles.append(ohlc(9, high=13, low=7))
    bars = make_bars(candles, start=utc(2026, 9, 7))
    output = OrderBlockDetector().run(detector_input(bars, crypto_calendar()))
    assert output.features[0].details["traversed"] is True
    assert output.features[0].details["revisited"] is True
    assert "traversed" not in output.events[0].details
    assert "revisited" not in output.events[0].details
    first = next(item for item in output.transitions if item.to_state == "revisited")
    assert first.details["traversed"] is False
    assert (
        replay_violations(
            incremental_replay(OrderBlockDetector(), detector_input(bars, crypto_calendar()))
        )
        == []
    )


def test_order_block_body_zone_keeps_extreme_invalidation() -> None:
    bars = make_bars(_order_block_candles(), start=utc(2026, 9, 7))
    output = OrderBlockDetector().run(
        detector_input(bars, crypto_calendar(), parameters={"use_body": True})
    )
    names = {level.name: level.price for level in output.events[0].levels}
    assert names["zone_lower"] == Decimal(9)
    assert names["zone_upper"] == Decimal(12)
    assert output.events[0].details["invalidation"] == "8"
    assert output.events[0].details["use_body"] is True
    assert output.events[0].detector == "order_block"


def test_order_block_warns_when_atr_is_not_ready() -> None:
    highs = [5, 6, 7, 12, 7, 6, 5, 5, 5, 13]
    closes = [4, 4, 4, 4, 4, 4, 4, 4, 4, 13]
    candles = [
        ohlc(close, high=max(close, high), low=1) for close, high in zip(closes, highs, strict=True)
    ]
    output = OrderBlockDetector().run(
        detector_input(make_bars(candles, start=utc(2026, 9, 7)), crypto_calendar())
    )
    assert output.events == []
    assert any("ATR warm-up" in warning for warning in output.warnings)


def test_divergence_levels_confirm_at_the_second_pivot() -> None:
    closes = [Decimal(50) - Decimal(index) for index in range(15)]
    closes.extend(Decimal(36) + Decimal(index) for index in range(1, 10))
    lows = [12] * len(closes)
    lows[14] = 10
    lows[20] = 8
    candles = [
        ohlc(format(close, "f"), low=low, high=format(close, "f"))
        for close, low in zip(closes, lows, strict=True)
    ]
    bars = make_bars(candles, start=utc(2026, 9, 7))
    output = RsiDivergenceDetector().run(detector_input(bars, crypto_calendar()))
    event = next(item for item in output.events if item.direction == "bullish")
    feature = next(item for item in output.features if item.direction == "bullish")
    names = {level.name: level.price for level in event.levels}
    assert names["price_first"] == Decimal(10)
    assert names["price_second"] == Decimal(8)
    assert event.details["kind"] == "regular"
    assert feature.origin_time == bars[20].origin_time
    assert feature.confirmation_time == bars[23].origin_time + timedelta(minutes=15)
    assert feature.parameters["include_hidden"] is False
    assert feature.calc_version == CALC_VERSION
    assert feature.instrument_id == INSTRUMENT_ID
    assert feature.contract_code == "ESZ6"
    assert feature.timeframe == "15m"
    assert feature.session == "current_session"
    assert feature.state == "confirmed"
    assert feature.snapshot_id == SNAPSHOT_ID
    assert feature.data_revision == REVISION
    assert feature.provenance == "fixture"
    assert feature.id is not None
    assert (
        replay_violations(
            incremental_replay(RsiDivergenceDetector(), detector_input(bars, crypto_calendar()))
        )
        == []
    )


def test_replay_flags_an_event_created_by_a_later_bar() -> None:
    highs = [5, 6, 7, 12, 7, 6, 5, 5]
    bars = make_bars([ohlc(4, high=high, low=1) for high in highs], start=utc(2026, 9, 7))
    steps = incremental_replay(SwingPivotDetector(), detector_input(bars, crypto_calendar()))
    assert replay_violations(steps) == []
    confirmed = next(step for step in steps if step.events)
    original = confirmed.events[0]
    bogus = original.model_copy(
        update={
            "id": UUID("33333333-3333-4333-8333-333333333333"),
            "feature_id": UUID("44444444-4444-4444-8444-444444444444"),
            "origin_time": original.origin_time - timedelta(minutes=15),
        }
    )
    late = ReplayStep(
        as_of=confirmed.as_of + timedelta(minutes=15),
        events=(*confirmed.events, bogus),
        transitions=(),
    )
    violations = replay_violations([confirmed, late])
    assert any("created by a later bar" in item for item in violations)


def test_six_detectors_do_not_rewrite_prior_events() -> None:
    candles = [_default_candle() for _ in range(20)]
    candles[3] = ohlc(12, high=30, low=10)
    candles[8] = ohlc(20, high=22, low=11, open_=11)
    candles[10] = ohlc(28, high=30, low=24, open_=24)
    bars = make_bars(candles, start=utc(2026, 9, 7))
    names: tuple[DetectorName, ...] = (
        "volume_profile",
        "fvg",
        "liquidity_sweep",
        "bos",
        "order_block",
        "rsi_divergence",
    )
    registry = default_registry()
    for name in names:
        parameters: dict[str, JsonValue] | None = (
            {"bar_approximation": True} if name == "volume_profile" else None
        )
        data = detector_input(bars, crypto_calendar(), parameters=parameters)
        detector = registry.get(name, CALC_VERSION)
        assert replay_violations(incremental_replay(detector, data)) == []
