"""Sweeps, breaks, order blocks, divergence, and no-lookahead replay."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from tests.unit.ta.helpers import crypto_calendar, detector_input, make_bars, ohlc, utc

from trading_core.ta import incremental_replay, replay_violations
from trading_core.ta.detectors.bos import BosDetector
from trading_core.ta.detectors.fvg import FvgDetector
from trading_core.ta.detectors.liquidity_sweep import LiquiditySweepDetector
from trading_core.ta.detectors.order_block import OrderBlockDetector
from trading_core.ta.detectors.rsi_divergence import RsiDivergenceDetector
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
