"""Volume profile hand numbers, approximation label, and trade-print requirement."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from tests.conftest import FIXTURES_DIR
from tests.unit.ta.helpers import (
    crypto_calendar,
    detector_input,
    make_bars,
    make_trades,
    ohlc,
    short_session_calendar,
    utc,
    weekday_calendar,
)

from trading_core.ta import incremental_replay, replay_violations
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
    assert names["hvn_2"] == "111"
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


def _profile_window() -> ProfileWindow:
    start = utc(2026, 9, 7)
    return ProfileWindow(
        start=start,
        end=start + timedelta(minutes=15),
        origin_time=start,
        confirmation_time=start + timedelta(minutes=15),
        complete=True,
        contract_code="ESZ6",
        session_day=None,
        bar_indexes=(0,),
    )


def test_value_area_expansion_tie_breaks() -> None:
    equal = build_profile(
        [Decimal(100), Decimal(101), Decimal(102)],
        [Decimal(2), Decimal(5), Decimal(2)],
        _profile_window(),
        "trades",
    )
    assert equal.poc == Decimal(101)
    assert equal.val == Decimal(100)
    assert equal.vah == Decimal(101)

    # Volumes 0,1,0,10,0,1,5. The equal-volume step closer to the POC keeps VAL at 101.
    # Always choosing the lower bin would pull VAL down to 100.
    closer = build_profile(
        [Decimal(100 + index) for index in range(7)],
        [Decimal(item) for item in (0, 1, 0, 10, 0, 1, 5)],
        _profile_window(),
        "trades",
    )
    assert closer.poc == Decimal(103)
    assert closer.val == Decimal(101)
    assert closer.vah == Decimal(105)
    assert closer.covered == Decimal(12)


def test_even_plateau_uses_the_lower_middle() -> None:
    profile = build_profile(
        [Decimal(100 + index) for index in range(9)],
        [Decimal(item) for item in (1, 1, 1, 8, 8, 1, 1, 1, 1)],
        _profile_window(),
        "trades",
    )
    assert profile.poc == Decimal(103)
    assert profile.hvn == (Decimal(103),)
    assert profile.lvn == ()
    assert profile.p25 == Decimal(1)
    assert profile.p75 == Decimal(9) / Decimal(2)


def test_node_percentiles_ignore_smoothed_zeros() -> None:
    profile = build_profile(
        [Decimal(100 + index) for index in range(11)],
        [
            Decimal(5),
            Decimal(5),
            Decimal(5),
            Decimal(0),
            Decimal(0),
            Decimal(0),
            Decimal(0),
            Decimal(0),
            Decimal(5),
            Decimal(5),
            Decimal(5),
        ],
        _profile_window(),
        "trades",
    )
    assert profile.p25 == Decimal(25) / Decimal(12)
    assert profile.p75 == Decimal(55) / Decimal(12)
    assert profile.p25 != Decimal(0)


def test_prints_outside_completed_bars_are_not_profile_volume() -> None:
    start = utc(2026, 9, 7, 9, 0)
    bars = make_bars([ohlc(100, high=101, low=100)], start=start, volume="1")
    trades = make_trades(
        [
            (start + timedelta(seconds=1), "100", "1"),
            (start + timedelta(minutes=20), "101", "50"),
        ]
    )
    output = VolumeProfileDetector().run(
        detector_input(bars, short_session_calendar(), trades=trades, session="current_session")
    )
    assert output.features[0].details["volume_source"] == "trades"
    assert output.features[0].details["total"] == "1"
    assert BAR_APPROXIMATION_WARNING not in output.warnings


def test_partial_tape_is_missing_coverage_not_zero() -> None:
    start = utc(2026, 9, 7, 9, 0)
    bars = make_bars([ohlc(100, high=101, low=100)], start=start, volume="10")
    trades = make_trades([(start + timedelta(seconds=1), "100", "1")])
    data = detector_input(bars, short_session_calendar(), trades=trades)
    with pytest.raises(InsufficientDataError, match="missing coverage is not zero volume"):
        VolumeProfileDetector().run(data)
    approximate = VolumeProfileDetector().run(
        detector_input(
            bars,
            short_session_calendar(),
            trades=trades,
            parameters={"bar_approximation": True},
        )
    )
    assert approximate.features[0].details["volume_source"] == "bar_range_approximation"
    assert any("do not match bar volume" in warning for warning in approximate.warnings)
    assert BAR_APPROXIMATION_WARNING in approximate.warnings


def test_prior_session_confirms_when_the_next_session_starts() -> None:
    calendar = short_session_calendar()
    day1 = [utc(2026, 9, 7, 9, minute) for minute in (0, 15, 30, 45)]
    day2 = [utc(2026, 9, 8, 9, minute) for minute in (0, 15, 30, 45)]
    day3 = [utc(2026, 9, 9, 9, minute) for minute in (0, 15, 30, 45)]
    bars = make_bars(
        [ohlc(100, high=101, low=100)] * 12,
        start=day1[0],
        origins=day1 + day2 + day3,
        volume="1",
    )
    current = VolumeProfileDetector().run(
        detector_input(
            bars, calendar, session="current_session", parameters={"bar_approximation": True}
        )
    )
    assert sorted(str(event.details["session_day"]) for event in current.events) == [
        "2026-09-07",
        "2026-09-08",
        "2026-09-09",
    ]
    prior = VolumeProfileDetector().run(
        detector_input(
            bars, calendar, session="prior_session", parameters={"bar_approximation": True}
        )
    )
    by_day = {str(event.details["session_day"]): event for event in prior.events}
    assert set(by_day) == {"2026-09-07", "2026-09-08"}
    assert by_day["2026-09-07"].event_time == day2[0] + timedelta(minutes=15)
    assert by_day["2026-09-08"].event_time == day3[0] + timedelta(minutes=15)
    steps = incremental_replay(
        VolumeProfileDetector(),
        detector_input(
            bars, calendar, session="prior_session", parameters={"bar_approximation": True}
        ),
    )
    assert replay_violations(steps) == []
    current_steps = incremental_replay(
        VolumeProfileDetector(),
        detector_input(
            bars, calendar, session="current_session", parameters={"bar_approximation": True}
        ),
    )
    assert replay_violations(current_steps) == []


def test_composite_stays_on_one_contract_and_anchored_is_one_window() -> None:
    calendar = short_session_calendar()
    day1 = [utc(2026, 9, 7, 9, minute) for minute in (0, 15, 30, 45)]
    day2 = [utc(2026, 9, 8, 9, minute) for minute in (0, 15, 30, 45)]
    day3 = [utc(2026, 9, 9, 9, minute) for minute in (0, 15, 30, 45)]
    bars = make_bars(
        [ohlc(100, high=101, low=100)] * 12,
        start=day1[0],
        origins=day1 + day2 + day3,
        volume="1",
    )
    composite = VolumeProfileDetector().run(
        detector_input(
            bars,
            calendar,
            session="composite",
            parameters={"bar_approximation": True, "session_count": 2},
        )
    )
    assert len(composite.events) == 2
    assert all(event.details["total"] == "8" for event in composite.events)
    assert (
        replay_violations(
            incremental_replay(
                VolumeProfileDetector(),
                detector_input(
                    bars,
                    calendar,
                    session="composite",
                    parameters={"bar_approximation": True, "session_count": 2},
                ),
            )
        )
        == []
    )
    mixed = make_bars(
        [ohlc(100, high=101, low=100)] * 8,
        start=day1[0],
        origins=day1 + day2,
        volume="1",
        contracts=["ESU6"] * 4 + ["ESZ6"] * 4,
    )
    with pytest.raises(InsufficientDataError, match="across contracts"):
        VolumeProfileDetector().run(
            detector_input(
                mixed,
                calendar,
                session="composite",
                parameters={"bar_approximation": True, "session_count": 2},
            )
        )
    anchored = VolumeProfileDetector().run(
        detector_input(
            bars[:4],
            calendar,
            session="anchored",
            parameters={
                "bar_approximation": True,
                "anchor_time": day1[0].isoformat(),
                "end_time": (day1[-1] + timedelta(minutes=15)).isoformat(),
            },
        )
    )
    assert len(anchored.events) == 1
    assert anchored.events[0].details["total"] == "4"


def test_overnight_without_rth_is_refused() -> None:
    start = utc(2026, 9, 7, 9)
    bars = make_bars([ohlc(100), ohlc(101)], start=start, volume="1")
    with pytest.raises(InsufficientDataError, match="overnight profile requires an RTH"):
        VolumeProfileDetector().run(
            detector_input(
                bars,
                weekday_calendar(),
                session="overnight",
                parameters={"bar_approximation": True},
            )
        )
