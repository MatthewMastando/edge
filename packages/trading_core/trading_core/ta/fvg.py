"""Fair value gaps on three consecutive completed bars.

Bullish when ``low(C) > high(A)`` by at least one tick, zone ``[high(A), low(C)]``.
Bearish when ``high(C) < low(A)`` by at least one tick, zone ``[high(C), low(A)]``.
The gap confirms at C's close. A missing bar, a scheduled session break, or a roll anywhere
between A and C excludes the pattern. Displacement is tagged from candle B against the ATR
known on the previous bar; it is null until that ATR exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from trading_core.ta.envelope import TransitionDraft, decimal_str
from trading_core.ta.series import PreparedSeries, bar_close_time

if TYPE_CHECKING:
    from datetime import datetime

    from pydantic import JsonValue

    from trading_core.domain.market import Bar
    from trading_core.domain.ta import FeatureState

Side = Literal["bullish", "bearish"]


@dataclass(frozen=True)
class Fvg:
    direction: Side
    index_a: int
    index_b: int
    index_c: int
    lower: Decimal
    upper: Decimal
    midpoint: Decimal
    displacement: bool | None
    contract_code: str | None


def find_fvgs(
    prepared: PreparedSeries,
    *,
    min_ticks: int,
    body_ratio: Decimal,
    atr: dict[int, Decimal],
) -> list[Fvg]:
    if min_ticks < 1:
        msg = "min_ticks must be at least 1"
        raise ValueError(msg)
    minimum = prepared.tick * min_ticks
    found: list[Fvg] = []
    bars = prepared.bars
    for index_c in range(2, len(bars)):
        index_a = index_c - 2
        index_b = index_c - 1
        if not prepared.consecutive(index_a, index_c):
            continue
        if bars[index_a].contract_code != bars[index_c].contract_code:
            continue
        gap = _gap(bars[index_a], bars[index_c], minimum)
        if gap is None:
            continue
        direction, lower, upper = gap
        found.append(
            Fvg(
                direction=direction,
                index_a=index_a,
                index_b=index_b,
                index_c=index_c,
                lower=lower,
                upper=upper,
                midpoint=(lower + upper) / Decimal(2),
                displacement=_displacement(bars[index_b], atr.get(index_a), body_ratio),
                contract_code=bars[index_b].contract_code,
            )
        )
    return found


def track_fvg(
    prepared: PreparedSeries, pattern: Fvg
) -> tuple[FeatureState, list[TransitionDraft], dict[str, JsonValue]]:
    """Lifecycle after confirmation. Details are the latest view, not the event snapshot."""
    bars = prepared.bars
    state: FeatureState = "confirmed"
    transitions: list[TransitionDraft] = []
    depth = Decimal(0)
    invalidated = False
    for index in range(pattern.index_c + 1, len(bars)):
        if bars[index].contract_code != pattern.contract_code:
            break
        if prepared.gaps[index - 1] in {"roll", "missing"}:
            break
        observation = _observe(pattern, bars[index])
        depth = max(depth, observation.depth)
        state, invalidated = _apply_observation(
            pattern, bars[index], observation, state, transitions, depth
        )
        if invalidated:
            break
    details = _live_details(pattern, depth, state)
    return state, transitions, details


def confirmation_details(pattern: Fvg) -> dict[str, JsonValue]:
    displacement: JsonValue
    displacement = None if pattern.displacement is None else pattern.displacement
    return {
        "index_a": pattern.index_a,
        "index_b": pattern.index_b,
        "index_c": pattern.index_c,
        "lower": decimal_str(pattern.lower),
        "upper": decimal_str(pattern.upper),
        "midpoint": decimal_str(pattern.midpoint),
        "displacement": displacement,
        "fill_depth": "0",
    }


def confirmation_time(prepared: PreparedSeries, pattern: Fvg) -> tuple[datetime, str]:
    bar = prepared.bars[pattern.index_c]
    return bar_close_time(bar), bar.origin_tz


@dataclass(frozen=True)
class _Observation:
    touched: bool
    midpoint: bool
    filled: bool
    invalidated: bool
    depth: Decimal


def _gap(bar_a: Bar, bar_c: Bar, minimum: Decimal) -> tuple[Side, Decimal, Decimal] | None:
    if bar_c.low - bar_a.high >= minimum:
        return "bullish", bar_a.high, bar_c.low
    if bar_a.low - bar_c.high >= minimum:
        return "bearish", bar_c.high, bar_a.low
    return None


def _displacement(bar: Bar, preceding_atr: Decimal | None, body_ratio: Decimal) -> bool | None:
    if preceding_atr is None:
        return None
    span = bar.high - bar.low
    if span == 0:
        return False
    body = abs(bar.close - bar.open)
    return body >= preceding_atr and (body / span) >= body_ratio


def _observe(pattern: Fvg, bar: Bar) -> _Observation:
    width = pattern.upper - pattern.lower
    if pattern.direction == "bullish":
        reach = pattern.upper - bar.low
        invalidated = bar.close < pattern.lower
    else:
        reach = bar.high - pattern.lower
        invalidated = bar.close > pattern.upper
    depth = Decimal(0) if width == 0 else min(Decimal(1), max(Decimal(0), reach / width))
    if invalidated:
        depth = Decimal(1)
    intersects = bar.low <= pattern.upper and bar.high >= pattern.lower
    midpoint_hit = bar.low <= pattern.midpoint <= bar.high
    filled = depth >= 1
    engaged = intersects or invalidated or filled
    return _Observation(
        touched=engaged,
        midpoint=midpoint_hit or invalidated,
        filled=filled,
        invalidated=invalidated,
        depth=depth,
    )


def _apply_observation(
    pattern: Fvg,
    bar: Bar,
    observation: _Observation,
    state: FeatureState,
    transitions: list[TransitionDraft],
    depth: Decimal,
) -> tuple[FeatureState, bool]:
    steps: list[tuple[bool, FeatureState]] = [
        (observation.touched, "touched"),
        (observation.midpoint, "midpoint_touched"),
        (depth > 0, "partially_filled"),
        (observation.filled, "filled"),
        (observation.invalidated, "invalidated"),
    ]
    invalidated = False
    for should, target in steps:
        if not should or _already(transitions, target):
            continue
        transitions.append(
            TransitionDraft(
                from_state=state,
                to_state=target,
                bar_time=bar_close_time(bar),
                bar_tz=bar.origin_tz,
                details={"fill_depth": decimal_str(depth), "direction": pattern.direction},
            )
        )
        state = target
        invalidated = target == "invalidated"
    return state, invalidated


def _already(transitions: list[TransitionDraft], target: FeatureState) -> bool:
    return any(item.to_state == target for item in transitions)


def _live_details(pattern: Fvg, depth: Decimal, state: FeatureState) -> dict[str, JsonValue]:
    details = confirmation_details(pattern)
    details["fill_depth"] = decimal_str(depth)
    details["state"] = state
    return details
