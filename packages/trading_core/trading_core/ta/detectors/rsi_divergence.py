"""RSI divergence detector. Hidden divergence stays off unless include_hidden is set."""

from __future__ import annotations

from typing import TYPE_CHECKING

from trading_core.ta.constants import (
    CALC_VERSION,
    RSI_DIV_MAX_SEPARATION,
    RSI_DIV_MIN_POINTS,
    RSI_DIV_MIN_SEPARATION,
    RSI_PERIOD,
)
from trading_core.ta.detectors.common import bind, finish, require_count, with_rolls
from trading_core.ta.divergence import Divergence, divergence_details, find_divergences
from trading_core.ta.envelope import FeatureDraft
from trading_core.ta.parsing import param_bool, param_decimal, param_int
from trading_core.ta.series import PreparedSeries, bar_close_time
from trading_core.ta.swings import detect_swings
from trading_core.ta.wilder import require_no_missing, rsi_by_index

if TYPE_CHECKING:
    from pydantic import JsonValue

    from trading_core.domain.common import CalcVersion, Direction, SessionScope
    from trading_core.domain.ta import DetectorName
    from trading_core.ta.interfaces import DetectorInput, DetectorOutput


class RsiDivergenceDetector:
    @property
    def name(self) -> DetectorName:
        return "rsi_divergence"

    @property
    def calc_version(self) -> CalcVersion:
        return CALC_VERSION

    def default_parameters(self) -> dict[str, JsonValue]:
        return with_rolls(
            {
                "min_separation": RSI_DIV_MIN_SEPARATION,
                "max_separation": RSI_DIV_MAX_SEPARATION,
                "min_points": format(RSI_DIV_MIN_POINTS, "f"),
                "include_hidden": False,
            }
        )

    def run(self, data: DetectorInput) -> DetectorOutput:
        params, prepared = bind(data, self.default_parameters())
        require_count(prepared, RSI_PERIOD + 1, "RSI divergence")
        require_no_missing(prepared, "RSI divergence")
        rsi = rsi_by_index(prepared, period=RSI_PERIOD, split_on=frozenset({"roll"}))
        found = find_divergences(
            prepared,
            detect_swings(prepared),
            rsi,
            min_separation=param_int(params, "min_separation"),
            max_separation=param_int(params, "max_separation"),
            min_points=param_decimal(params, "min_points"),
            include_hidden=param_bool(params, "include_hidden"),
        )
        drafts = _merge(prepared, found, data.session)
        warnings: list[str] = []
        if "roll" in prepared.gaps:
            warnings.append("RSI divergence does not pair pivots across a roll")
        return finish(
            name=self.name,
            data=data,
            prepared=prepared,
            params=params,
            drafts=drafts,
            warnings=warnings,
        )


def _merge(
    prepared: PreparedSeries, found: list[Divergence], session: SessionScope
) -> list[FeatureDraft]:
    grouped: dict[tuple[str, str | None], list[Divergence]] = {}
    order: list[tuple[str, str | None]] = []
    for item in found:
        origin = prepared.bars[item.second_index].origin_time.isoformat()
        key = (origin, item.contract_code)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(item)
    drafts: list[FeatureDraft] = []
    for key in order:
        items = grouped[key]
        second = prepared.bars[items[0].second_index]
        confirm = prepared.bars[items[0].confirmation_index]
        direction, details = _bundle(items)
        drafts.append(
            FeatureDraft(
                direction=direction,
                session=session,
                levels=[],
                state="confirmed",
                origin_time=second.origin_time,
                origin_tz=second.origin_tz,
                confirmation_time=bar_close_time(confirm),
                confirmation_tz=confirm.origin_tz,
                contract_code=items[0].contract_code,
                details=details,
            )
        )
    return drafts


def _bundle(items: list[Divergence]) -> tuple[Direction, dict[str, JsonValue]]:
    if len(items) == 1:
        return items[0].direction, divergence_details(items[0])
    directions = {item.direction for item in items}
    direction: Direction = items[0].direction if len(directions) == 1 else "neutral"
    signals: list[JsonValue] = [divergence_details(item) for item in items]
    return direction, {"signals": signals}
