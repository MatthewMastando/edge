"""Fair value gap detector."""

from __future__ import annotations

from typing import TYPE_CHECKING

from trading_core.ta.constants import (
    ATR_PERIOD,
    CALC_VERSION,
    DISPLACEMENT_BODY_RATIO,
    FVG_MIN_TICKS,
)
from trading_core.ta.detectors.common import bind, finish, price_level, require_count, with_rolls
from trading_core.ta.envelope import FeatureDraft
from trading_core.ta.fvg import Fvg, confirmation_details, confirmation_time, find_fvgs, track_fvg
from trading_core.ta.parsing import param_decimal, param_int
from trading_core.ta.wilder import atr_by_index

if TYPE_CHECKING:
    from pydantic import JsonValue

    from trading_core.domain.common import CalcVersion, SessionScope
    from trading_core.domain.ta import DetectorName
    from trading_core.ta.interfaces import DetectorInput, DetectorOutput
    from trading_core.ta.series import PreparedSeries


class FvgDetector:
    @property
    def name(self) -> DetectorName:
        return "fvg"

    @property
    def calc_version(self) -> CalcVersion:
        return CALC_VERSION

    def default_parameters(self) -> dict[str, JsonValue]:
        return with_rolls(
            {"min_ticks": FVG_MIN_TICKS, "body_ratio": format(DISPLACEMENT_BODY_RATIO, "f")}
        )

    def run(self, data: DetectorInput) -> DetectorOutput:
        params, prepared = bind(data, self.default_parameters())
        require_count(prepared, 3, "fair value gaps")
        atr = atr_by_index(
            prepared,
            period=ATR_PERIOD,
            split_on=frozenset({"roll", "missing"}),
            allow_short=True,
        )
        patterns = find_fvgs(
            prepared,
            min_ticks=param_int(params, "min_ticks"),
            body_ratio=param_decimal(params, "body_ratio"),
            atr=atr,
        )
        drafts = [_draft(prepared, pattern, data.session) for pattern in patterns]
        warnings: list[str] = []
        if any(gap != "ok" for gap in prepared.gaps):
            warnings.append("fair value gaps skip bars that are not one timeframe apart")
        return finish(
            name=self.name,
            data=data,
            prepared=prepared,
            params=params,
            drafts=drafts,
            warnings=warnings,
        )


def _draft(prepared: PreparedSeries, pattern: Fvg, session: SessionScope) -> FeatureDraft:
    origin = prepared.bars[pattern.index_b]
    confirmed_at, confirmed_tz = confirmation_time(prepared, pattern)
    state, transitions, live = track_fvg(prepared, pattern)
    levels = [
        price_level("zone_lower", pattern.lower, "zone_lower"),
        price_level("zone_upper", pattern.upper, "zone_upper"),
        price_level("midpoint", pattern.midpoint, "midpoint"),
    ]
    return FeatureDraft(
        direction=pattern.direction,
        session=session,
        levels=levels,
        state=state,
        origin_time=origin.origin_time,
        origin_tz=origin.origin_tz,
        confirmation_time=confirmed_at,
        confirmation_tz=confirmed_tz,
        contract_code=pattern.contract_code,
        details=live,
        event_levels=levels,
        event_details=confirmation_details(pattern),
        event_time=confirmed_at,
        transitions=transitions,
    )
