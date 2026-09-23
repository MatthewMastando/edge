"""Break of structure detector."""

from __future__ import annotations

from typing import TYPE_CHECKING

from trading_core.ta.constants import CALC_VERSION
from trading_core.ta.detectors.common import bind, finish, price_level, require_count, with_rolls
from trading_core.ta.envelope import FeatureDraft
from trading_core.ta.series import PreparedSeries, bar_close_time
from trading_core.ta.structure import StructureBreak, break_details, find_breaks
from trading_core.ta.swings import detect_swings

if TYPE_CHECKING:
    from pydantic import JsonValue

    from trading_core.domain.common import CalcVersion, SessionScope
    from trading_core.domain.ta import DetectorName
    from trading_core.ta.interfaces import DetectorInput, DetectorOutput


class BosDetector:
    @property
    def name(self) -> DetectorName:
        return "bos"

    @property
    def calc_version(self) -> CalcVersion:
        return CALC_VERSION

    def default_parameters(self) -> dict[str, JsonValue]:
        return with_rolls()

    def run(self, data: DetectorInput) -> DetectorOutput:
        params, prepared = bind(data, self.default_parameters())
        require_count(prepared, 7, "break of structure")
        breaks = find_breaks(prepared, detect_swings(prepared), prepared.tick)
        drafts = [_draft(prepared, item, data.session) for item in breaks]
        return finish(
            name=self.name, data=data, prepared=prepared, params=params, drafts=drafts, warnings=[]
        )


def _draft(prepared: PreparedSeries, item: StructureBreak, session: SessionScope) -> FeatureDraft:
    bar = prepared.bars[item.index]
    return FeatureDraft(
        direction=item.direction,
        session=session,
        levels=[price_level("broken_level", item.level)],
        state="confirmed",
        origin_time=bar.origin_time,
        origin_tz=bar.origin_tz,
        confirmation_time=bar_close_time(bar),
        confirmation_tz=bar.origin_tz,
        contract_code=bar.contract_code,
        details=break_details(item),
    )
