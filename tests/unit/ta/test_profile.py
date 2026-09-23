"""Volume profile hand numbers, approximation label, and trade-print requirement."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from tests.conftest import FIXTURES_DIR
from tests.unit.ta.helpers import crypto_calendar, detector_input, make_bars, make_trades, ohlc, utc

from trading_core.ta.constants import BAR_APPROXIMATION_WARNING
from trading_core.ta.detectors.volume_profile import VolumeProfileDetector
from trading_core.ta.interfaces import InsufficientDataError
from trading_core.ta.profile import ProfileWindow, build_profile, histogram_from_trades
from trading_core.ta.series import prepare


def _load() -> dict[str, object]:
    payload: object = json.loads((FIXTURES_DIR / "ta" / "volume_profile.json").read_text())
    assert isinstance(payload, dict)
    return {str(key): value for key, value in payload.items()}


def _strings(value: object) -> list[str]:
    assert isinstance(value, list)
    out: list[str] = []
    for item in value:
        assert isinstance(item, str)
        out.append(item)
    return out


def _text(raw: dict[str, object], key: str) -> str:
    value = raw[key]
    assert isinstance(value, str)
    return value


def test_hand_profile_matches_fixture() -> None:
    raw = _load()
    start = utc(2026, 9, 7)
    prices = _strings(raw["prices"])
    volumes = _strings(raw["volumes"])
    prints = [
        (start + timedelta(seconds=index + 1), price, size)
        for index, (price, size) in enumerate(zip(prices, volumes, strict=True))
    ]
    batch = make_trades(prints)
    bars = make_bars([ohlc(100, high=114, low=100)], start=start, volume="31")
    data = detector_input(
        bars,
        crypto_calendar(),
        session="fixed_range",
        trades=batch,
        parameters={
            "range_start": start.isoformat(),
            "range_end": (start + timedelta(minutes=15)).isoformat(),
        },
    )
    prepared = prepare(data, [])
    prices_out, volumes_out = histogram_from_trades(list(batch.trades), prepared.tick)
    window = ProfileWindow(
        start=start,
        end=start + timedelta(minutes=15),
        origin_time=start,
        confirmation_time=start + timedelta(minutes=15),
        complete=True,
        contract_code="ESZ6",
        session_day=None,
        bar_indexes=(0,),
    )
    profile = build_profile(prices_out, volumes_out, window, "trades")
    assert format(profile.poc, "f") == _text(raw, "poc")
    assert format(profile.val, "f") == _text(raw, "val")
    assert format(profile.vah, "f") == _text(raw, "vah")
    assert format(profile.covered, "f") == _text(raw, "covered")
    assert format(profile.covered / profile.total, "f") == _text(raw, "achieved_coverage")
    assert profile.p25 is not None and format(profile.p25, "f") == _text(raw, "p25")
    assert profile.p75 is not None and format(profile.p75, "f") == _text(raw, "p75")
    assert [format(price, "f") for price in profile.hvn] == _strings(raw["hvn"])
    assert [format(price, "f") for price in profile.lvn] == _strings(raw["lvn"])

    output = VolumeProfileDetector().run(data)
    assert len(output.events) == 1
    assert output.events[0].details["achieved_coverage"] == _text(raw, "achieved_coverage")
    assert output.events[0].details["volume_source"] == "trades"
    names = {level.name: format(level.price, "f") for level in output.events[0].levels}
    assert names["poc"] == "105"
    assert names["vah"] == "111"
    assert names["val"] == "100"
    assert names["hvn"] == "105"
    assert names["lvn"] == "108"
    assert BAR_APPROXIMATION_WARNING not in output.warnings


def test_bars_alone_are_not_exact_volume() -> None:
    bars = make_bars([ohlc(100, high=114, low=100)], start=utc(2026, 9, 7), volume="31")
    data = detector_input(
        bars,
        crypto_calendar(),
        session="fixed_range",
        parameters={
            "range_start": utc(2026, 9, 7).isoformat(),
            "range_end": (utc(2026, 9, 7) + timedelta(minutes=15)).isoformat(),
        },
    )
    with pytest.raises(InsufficientDataError, match="not exact volume-at-price"):
        VolumeProfileDetector().run(data)


def test_bar_approximation_is_labeled() -> None:
    start = utc(2026, 9, 7)
    bars = make_bars([ohlc(100, high=102, low=100)], start=start, volume="3")
    end = start + timedelta(minutes=15)
    output = VolumeProfileDetector().run(
        detector_input(
            bars,
            crypto_calendar(),
            session="fixed_range",
            parameters={
                "bar_approximation": True,
                "range_start": start.isoformat(),
                "range_end": end.isoformat(),
            },
        )
    )
    assert BAR_APPROXIMATION_WARNING in output.warnings
    assert output.features[0].details["volume_source"] == "bar_range_approximation"
    assert output.events[0].details["volume_source"] == "bar_range_approximation"


def test_incomplete_window_does_not_log_an_event() -> None:
    start = utc(2026, 9, 7)
    bars = make_bars([ohlc(100, high=102, low=100)], start=start, volume="3")
    output = VolumeProfileDetector().run(
        detector_input(
            bars,
            crypto_calendar(),
            session="fixed_range",
            parameters={
                "bar_approximation": True,
                "range_start": start.isoformat(),
                "range_end": (start + timedelta(hours=2)).isoformat(),
            },
        )
    )
    assert output.features[0].state == "pending"
    assert output.events == []
    assert Decimal(str(output.features[0].details["total"])) == Decimal(3)
