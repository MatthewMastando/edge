"""Volume profile detector.

Trade prints are exact volume-at-price. Bars alone are refused unless
``bar_approximation`` is set, and that result is labeled as a range approximation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from trading_core.ta.constants import BAR_APPROXIMATION_WARNING, CALC_VERSION, COMPOSITE_SESSIONS
from trading_core.ta.detectors.common import bind, finish, price_level, with_rolls
from trading_core.ta.envelope import FeatureDraft, decimal_str
from trading_core.ta.interfaces import DetectorInput, DetectorOutput, InsufficientDataError
from trading_core.ta.parsing import param_bool, param_int, param_optional_time
from trading_core.ta.profile import (
    ProfileWindow,
    VolumeProfile,
    assert_trade_coverage,
    build_profile,
    histogram_from_bars,
    histogram_from_trades,
    select_windows,
    trade_coverage_matches,
    trades_for_bars,
)

if TYPE_CHECKING:
    from decimal import Decimal

    from pydantic import JsonValue

    from trading_core.domain.common import CalcVersion, SessionScope
    from trading_core.domain.market import Bar, Trade
    from trading_core.domain.ta import DetectorName, FeatureState, Level
    from trading_core.ta.series import PreparedSeries

_NO_PRINTS = (
    "volume profile requires trade prints; bar volume is not exact volume-at-price. "
    "Set bar_approximation to label a uniform range approximation"
)


class VolumeProfileDetector:
    @property
    def name(self) -> DetectorName:
        return "volume_profile"

    @property
    def calc_version(self) -> CalcVersion:
        return CALC_VERSION

    def default_parameters(self) -> dict[str, JsonValue]:
        return with_rolls(
            {
                "bar_approximation": False,
                "session_count": COMPOSITE_SESSIONS,
                "anchor_time": "",
                "end_time": "",
                "range_start": "",
                "range_end": "",
            }
        )

    def run(self, data: DetectorInput) -> DetectorOutput:
        params, prepared = bind(data, self.default_parameters())
        approximate = param_bool(params, "bar_approximation")
        trades = None if data.trades is None else list(data.trades.trades)
        if trades is None and not approximate:
            raise InsufficientDataError(_NO_PRINTS)
        windows = select_windows(
            prepared,
            data.calendar,
            data.session,
            session_count=param_int(params, "session_count"),
            anchor_time=param_optional_time(params, "anchor_time"),
            end_time=param_optional_time(params, "end_time"),
            range_start=param_optional_time(params, "range_start"),
            range_end=param_optional_time(params, "range_end"),
        )
        built = [
            _one(prepared, _bars(prepared, window), trades, window, approximate)
            for window in windows
        ]
        warnings: list[str] = []
        if any(item.profile.source != "trades" for item in built):
            warnings.append(BAR_APPROXIMATION_WARNING)
        for item in built:
            for warning in item.warnings:
                if warning not in warnings:
                    warnings.append(warning)
        drafts = [_draft(prepared, item.profile, data.session, item.warnings) for item in built]
        return finish(
            name=self.name,
            data=data,
            prepared=prepared,
            params=params,
            drafts=drafts,
            warnings=warnings,
        )


def _bars(prepared: PreparedSeries, window: ProfileWindow) -> list[Bar]:
    return [prepared.bars[index] for index in window.bar_indexes]


@dataclass(frozen=True)
class _BuiltProfile:
    profile: VolumeProfile
    warnings: list[str]


def _one(
    prepared: PreparedSeries,
    bars: list[Bar],
    trades: list[Trade] | None,
    window: ProfileWindow,
    approximate: bool,
) -> _BuiltProfile:
    selected = [] if trades is None else trades_for_bars(bars, trades)
    if trades is not None and trade_coverage_matches(bars, selected):
        prices, volumes = histogram_from_trades(selected, prepared.tick)
        return _BuiltProfile(build_profile(prices, volumes, window, "trades"), [])
    if not approximate:
        if trades is not None:
            assert_trade_coverage(bars, selected)
        raise InsufficientDataError(_NO_PRINTS)
    warnings: list[str] = []
    if trades is not None:
        warnings.append("trade prints do not match bar volume; bar-range approximation used")
    prices, volumes = histogram_from_bars(bars, prepared.tick)
    return _BuiltProfile(
        build_profile(prices, volumes, window, "bar_range_approximation"), warnings
    )


def _draft(
    prepared: PreparedSeries,
    profile: VolumeProfile,
    session: SessionScope,
    extra_warnings: list[str],
) -> FeatureDraft:
    window = profile.window
    state: FeatureState = "confirmed" if window.complete else "pending"
    last = prepared.bars[window.bar_indexes[-1]]
    warnings = [BAR_APPROXIMATION_WARNING] if profile.source != "trades" else []
    warnings.extend(extra_warnings)
    levels = _levels(profile)
    details = _details(profile, prepared.tick)
    confirmed = window.confirmation_time
    return FeatureDraft(
        direction="neutral",
        session=session,
        levels=levels,
        state=state,
        origin_time=window.origin_time,
        origin_tz=last.origin_tz,
        confirmation_time=confirmed,
        confirmation_tz=last.origin_tz if confirmed is not None else None,
        contract_code=window.contract_code,
        details=details,
        warnings=warnings,
        event_levels=levels if state == "confirmed" else None,
        event_details=details if state == "confirmed" else None,
        event_time=confirmed,
    )


def _levels(profile: VolumeProfile) -> list[Level]:
    levels = [
        price_level("poc", profile.poc, "node"),
        price_level("vah", profile.vah, "zone_upper"),
        price_level("val", profile.val, "zone_lower"),
    ]
    levels.extend(_named(profile.hvn, "hvn"))
    levels.extend(_named(profile.lvn, "lvn"))
    return levels


def _named(prices: tuple[Decimal, ...], stem: str) -> list[Level]:
    found: list[Level] = []
    for index, price in enumerate(prices):
        label = stem if index == 0 else f"{stem}_{index + 1}"
        found.append(price_level(label, price, "node"))
    return found


def _details(profile: VolumeProfile, tick: Decimal) -> dict[str, JsonValue]:
    coverage = profile.covered / profile.total
    prices: list[JsonValue] = [decimal_str(price) for price in profile.prices]
    volumes: list[JsonValue] = [decimal_str(volume) for volume in profile.volumes]
    day = profile.window.session_day
    return {
        "volume_source": profile.source,
        "bin_width": decimal_str(tick),
        "total": decimal_str(profile.total),
        "covered": decimal_str(profile.covered),
        "achieved_coverage": format(coverage, "f"),
        "target": "0.70",
        "p25": None if profile.p25 is None else decimal_str(profile.p25),
        "p75": None if profile.p75 is None else decimal_str(profile.p75),
        "prices": prices,
        "volumes": volumes,
        "complete": profile.window.complete,
        "session_day": None if day is None else day.isoformat(),
    }
