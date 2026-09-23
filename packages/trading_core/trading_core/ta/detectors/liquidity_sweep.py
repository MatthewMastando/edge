"""Liquidity sweep detector."""

from __future__ import annotations

from typing import TYPE_CHECKING

from trading_core.ta.constants import CALC_VERSION
from trading_core.ta.detectors.common import bind, finish, price_level, with_rolls
from trading_core.ta.envelope import FeatureDraft
from trading_core.ta.liquidity import Sweep, collect_levels, find_sweeps, sweep_details
from trading_core.ta.series import PreparedSeries, bar_close_time
from trading_core.ta.swings import detect_pools, detect_swings

if TYPE_CHECKING:
    from pydantic import JsonValue

    from trading_core.domain.common import CalcVersion, SessionScope
    from trading_core.domain.ta import DetectorName, Level
    from trading_core.ta.interfaces import DetectorInput, DetectorOutput


class LiquiditySweepDetector:
    @property
    def name(self) -> DetectorName:
        return "liquidity_sweep"

    @property
    def calc_version(self) -> CalcVersion:
        return CALC_VERSION

    def default_parameters(self) -> dict[str, JsonValue]:
        return with_rolls()

    def run(self, data: DetectorInput) -> DetectorOutput:
        params, prepared = bind(data, self.default_parameters())
        swings = detect_swings(prepared)
        pools = detect_pools(prepared, prepared.tick)
        levels = collect_levels(prepared, data.calendar, swings, pools)
        sweeps = find_sweeps(prepared, levels, prepared.tick)
        drafts = [_draft(prepared, sweep, data.session) for sweep in sweeps]
        return finish(
            name=self.name, data=data, prepared=prepared, params=params, drafts=drafts, warnings=[]
        )


def _draft(prepared: PreparedSeries, sweep: Sweep, session: SessionScope) -> FeatureDraft:
    bar = prepared.bars[sweep.index]
    names: dict[str, int] = {}
    levels: list[Level] = []
    for hit in sweep.hits:
        base = hit.level.source
        seen = names.get(base, 0)
        names[base] = seen + 1
        label = base if seen == 0 else f"{base}_{seen + 1}"
        levels.append(price_level(label, hit.level.price))
    return FeatureDraft(
        direction=sweep.direction,
        session=session,
        levels=levels,
        state="confirmed",
        origin_time=bar.origin_time,
        origin_tz=bar.origin_tz,
        confirmation_time=bar_close_time(bar),
        confirmation_tz=bar.origin_tz,
        contract_code=sweep.contract_code,
        details=sweep_details(prepared, sweep),
    )
