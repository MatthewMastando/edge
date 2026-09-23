"""Order block detector."""

from __future__ import annotations

from typing import TYPE_CHECKING

from trading_core.ta.constants import (
    ATR_PERIOD,
    BOS_TICKS,
    CALC_VERSION,
    DISPLACEMENT_BODY_RATIO,
    OB_LOOKBACK,
)
from trading_core.ta.detectors.common import bind, finish, price_level, require_count, with_rolls
from trading_core.ta.envelope import FeatureDraft, decimal_str
from trading_core.ta.parsing import param_bool, param_decimal, param_int
from trading_core.ta.series import PreparedSeries, bar_close_time
from trading_core.ta.structure import OrderBlock, find_breaks, find_order_blocks, track_order_block
from trading_core.ta.swings import detect_swings
from trading_core.ta.wilder import atr_by_index

if TYPE_CHECKING:
    from pydantic import JsonValue

    from trading_core.domain.common import CalcVersion, SessionScope
    from trading_core.domain.ta import DetectorName
    from trading_core.ta.interfaces import DetectorInput, DetectorOutput


class OrderBlockDetector:
    @property
    def name(self) -> DetectorName:
        return "order_block"

    @property
    def calc_version(self) -> CalcVersion:
        return CALC_VERSION

    def default_parameters(self) -> dict[str, JsonValue]:
        return with_rolls(
            {
                "body_ratio": format(DISPLACEMENT_BODY_RATIO, "f"),
                "lookback": OB_LOOKBACK,
                "use_body": False,
            }
        )

    def run(self, data: DetectorInput) -> DetectorOutput:
        params, prepared = bind(data, self.default_parameters())
        require_count(prepared, 7, "order blocks")
        atr = atr_by_index(
            prepared,
            period=ATR_PERIOD,
            split_on=frozenset({"roll", "missing"}),
            allow_short=True,
        )
        breaks = find_breaks(prepared, detect_swings(prepared), prepared.tick * BOS_TICKS)
        blocks, skipped_atr = find_order_blocks(
            prepared,
            breaks,
            atr,
            body_ratio=param_decimal(params, "body_ratio"),
            lookback=param_int(params, "lookback"),
            use_body=param_bool(params, "use_body"),
        )
        use_body = param_bool(params, "use_body")
        drafts = [_draft(prepared, block, data.session, use_body) for block in blocks]
        warnings: list[str] = []
        if skipped_atr:
            warnings.append("order block skipped a break because ATR warm-up was incomplete")
        return finish(
            name=self.name,
            data=data,
            prepared=prepared,
            params=params,
            drafts=drafts,
            warnings=warnings,
        )


def _draft(
    prepared: PreparedSeries, block: OrderBlock, session: SessionScope, use_body: bool
) -> FeatureDraft:
    origin = prepared.bars[block.candle_index]
    confirm = prepared.bars[block.break_index]
    state, transitions, traversed = track_order_block(prepared, block)
    levels = [
        price_level("zone_lower", block.zone_lower, "zone_lower"),
        price_level("zone_upper", block.zone_upper, "zone_upper"),
    ]
    snapshot: dict[str, JsonValue] = {
        "candle_index": block.candle_index,
        "break_index": block.break_index,
        "zone_lower": decimal_str(block.zone_lower),
        "zone_upper": decimal_str(block.zone_upper),
        "body_lower": decimal_str(block.body_lower),
        "body_upper": decimal_str(block.body_upper),
        "invalidation": decimal_str(block.invalidation),
        "use_body": use_body,
    }
    revisited = any(item.to_state == "revisited" for item in transitions)
    live = dict(snapshot)
    live["revisited"] = revisited
    live["traversed"] = traversed
    return FeatureDraft(
        direction=block.direction,
        session=session,
        levels=levels,
        state=state,
        origin_time=origin.origin_time,
        origin_tz=origin.origin_tz,
        confirmation_time=bar_close_time(confirm),
        confirmation_tz=confirm.origin_tz,
        contract_code=block.contract_code,
        details=live,
        event_levels=levels,
        event_details=dict(snapshot),
        event_time=bar_close_time(confirm),
        transitions=transitions,
    )
