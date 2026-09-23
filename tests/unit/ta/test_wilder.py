"""Wilder RSI(14) and ATR(14) against fixtures/ta/wilder.json."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from tests.conftest import FIXTURES_DIR
from tests.unit.ta.helpers import crypto_calendar, detector_input, make_bars, ohlc, utc

from trading_core.domain.market import Bar
from trading_core.ta import CALC_VERSION
from trading_core.ta.detectors.supporting import AtrDetector, RsiDetector
from trading_core.ta.interfaces import InsufficientDataError
from trading_core.ta.wilder import wilder_atr, wilder_rsi


def _load() -> dict[str, object]:
    payload: object = json.loads((FIXTURES_DIR / "ta" / "wilder.json").read_text())
    assert isinstance(payload, dict)
    return {str(key): value for key, value in payload.items()}


def _string_list(value: object) -> list[str]:
    assert isinstance(value, list)
    out: list[str] = []
    for item in value:
        assert isinstance(item, str)
        out.append(item)
    return out


def _string_map(value: object) -> dict[str, str]:
    assert isinstance(value, dict)
    out: dict[str, str] = {}
    for key, item in value.items():
        assert isinstance(key, str)
        assert isinstance(item, str)
        out[key] = item
    return out


def _bars_from_closes(closes: list[Decimal]) -> list[Bar]:
    candles = [ohlc(format(close, "f")) for close in closes]
    return make_bars(candles, start=utc(2026, 9, 7))


def test_fixture_rsi_matches_library() -> None:
    raw = _load()
    closes = [Decimal(item) for item in _string_list(raw["closes"])]
    expected = _string_map(raw["rsi"])
    library = wilder_rsi(closes)
    assert [format(point.value, "f") for point in library] == [expected["14"], expected["15"]]
    assert library[0].index == 14

    output = RsiDetector().run(detector_input(_bars_from_closes(closes), crypto_calendar()))
    assert output.features[0].calc_version == CALC_VERSION
    assert output.features[0].details["value"] == expected["14"]
    assert output.features[1].details["value"] == expected["15"]
    first = output.features[0]
    assert first.confirmation_time == first.origin_time + timedelta(minutes=15)
    assert len(output.events) == len(output.features)


def test_rsi_zero_average_cases() -> None:
    raw = _load()
    expected = _string_map(raw["rsi_zero_average"])
    flat = [Decimal(10)] * 16
    rising = [Decimal(10) + Decimal(index) for index in range(16)]
    falling = [Decimal(40) - Decimal(index) for index in range(16)]
    assert format(wilder_rsi(flat)[0].value, "f") == expected["flat"]
    assert format(wilder_rsi(rising)[0].value, "f") == expected["rising"]
    assert format(wilder_rsi(falling)[0].value, "f") == expected["falling"]
    flat_out = RsiDetector().run(detector_input(_bars_from_closes(flat), crypto_calendar()))
    assert flat_out.features[0].details["value"] == expected["flat"]


def test_atr_smoothing_matches_fixture() -> None:
    """TR is 1 on bars 1..14 and 15 on bar 15. The seed is not the smoothed value."""
    raw = _load()
    expected = _string_map(raw["atr_smoothing"])
    candles = [ohlc(100, high=101, low=100)] * 15
    candles.append(ohlc(100, high=115, low=100))
    bars = make_bars(candles, start=utc(2026, 9, 7))
    points = wilder_atr(bars)
    assert points[0].index == 14
    assert format(points[0].value, "f") == expected["index_14"]
    assert points[1].index == 15
    assert format(points[1].value, "f") == expected["index_15"]
    output = AtrDetector().run(detector_input(bars, crypto_calendar()))
    assert output.features[0].details["value"] == expected["index_14"]
    assert output.features[1].details["value"] == expected["index_15"]


def test_atr_matches_true_range_seed() -> None:
    candles = []
    for index in range(16):
        close = Decimal(100) + Decimal(index)
        candles.append(
            ohlc(format(close, "f"), high=format(close + 1, "f"), low=format(close - 1, "f"))
        )
    bars = make_bars(candles, start=utc(2026, 9, 7))
    assert [point.value for point in wilder_atr(bars)] == [Decimal(2), Decimal(2)]
    output = AtrDetector().run(detector_input(bars, crypto_calendar()))
    assert output.features[0].details["value"] == "2"
    assert output.features[0].detector == "atr"


def test_short_series_is_rejected() -> None:
    bars = make_bars([ohlc(1)] * 14, start=utc(2026, 9, 7))
    data = detector_input(bars, crypto_calendar())
    with pytest.raises(InsufficientDataError, match="warm-up"):
        RsiDetector().run(data)
    with pytest.raises(InsufficientDataError, match="warm-up"):
        AtrDetector().run(data)
