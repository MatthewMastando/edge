"""Shared detector plumbing. Algorithm modules stay free of the registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from trading_core.ta.constants import CALC_VERSION
from trading_core.ta.envelope import FeatureDraft, build_output, decimal_str, level
from trading_core.ta.interfaces import DetectorInput, DetectorOutput, InsufficientDataError
from trading_core.ta.parsing import param_roll_times, resolve_parameters
from trading_core.ta.series import PreparedSeries, bar_close_time, prepare

if TYPE_CHECKING:
    from decimal import Decimal

    from pydantic import JsonValue

    from trading_core.domain.common import Direction, SessionScope
    from trading_core.domain.market import Bar
    from trading_core.domain.ta import DetectorName, FeatureState, Level, LevelRole


def with_rolls(extra: dict[str, JsonValue] | None = None) -> dict[str, JsonValue]:
    params: dict[str, JsonValue] = {"roll_times": []}
    if extra:
        params.update(extra)
    return params


def bind(
    data: DetectorInput, defaults: dict[str, JsonValue]
) -> tuple[dict[str, JsonValue], PreparedSeries]:
    params = resolve_parameters(defaults, data.parameters)
    return params, prepare(data, param_roll_times(params))


def require_count(prepared: PreparedSeries, minimum: int, label: str) -> None:
    count = len(prepared.bars)
    if count < minimum:
        msg = f"{label} needs {minimum} completed bars; got {count}"
        raise InsufficientDataError(msg)


def price_level(name: str, price: Decimal, role: LevelRole = "level") -> Level:
    return level(name, price, role)


def bar_draft(
    bar: Bar,
    *,
    session: SessionScope,
    direction: Direction,
    state: FeatureState,
    levels: list[Level],
    details: dict[str, JsonValue],
    confirmation: bool = True,
    warnings: list[str] | None = None,
) -> FeatureDraft:
    return FeatureDraft(
        direction=direction,
        session=session,
        levels=levels,
        state=state,
        origin_time=bar.origin_time,
        origin_tz=bar.origin_tz,
        confirmation_time=bar_close_time(bar) if confirmation else None,
        confirmation_tz=bar.origin_tz if confirmation else None,
        contract_code=bar.contract_code,
        details=details,
        warnings=list(warnings or []),
    )


def finish(
    *,
    name: DetectorName,
    data: DetectorInput,
    prepared: PreparedSeries,
    params: dict[str, JsonValue],
    drafts: list[FeatureDraft],
    warnings: list[str],
) -> DetectorOutput:
    return build_output(
        detector=name,
        calc_version=CALC_VERSION,
        data=data,
        prepared=prepared,
        parameters=params,
        drafts=drafts,
        warnings=warnings,
    )


def value_details(index: int, value: Decimal) -> dict[str, JsonValue]:
    return {"index": index, "value": decimal_str(value)}
