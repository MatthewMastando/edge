"""Break of structure and the order block that displacement leaves behind.

BOS is a close at least one tick beyond the latest confirmed, still-unconsumed swing.
A wick that does not close through does not count. Structure is continuation when the
break agrees with the prior confirmed higher-high/higher-low or lower-high/lower-low
sequence, a possible structure change when it opposes that sequence, and unknown otherwise.

An order block is the latest opposite-color candle in the five completed bars before a
displacement break. Dojis are ignored. The zone is the candle's full high-low unless
``use_body`` is set. Invalidation always uses the candle extreme: a bullish block fails
on a close below its low, a bearish block on a close above its high.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from trading_core.ta.envelope import TransitionDraft, decimal_str
from trading_core.ta.series import PreparedSeries, bar_close_time

if TYPE_CHECKING:
    from decimal import Decimal

    from pydantic import JsonValue

    from trading_core.domain.market import Bar
    from trading_core.domain.ta import FeatureState
    from trading_core.ta.swings import Swing

BreakKind = Literal["continuation", "structure_change", "unknown"]
BreakSide = Literal["bullish", "bearish"]


@dataclass(frozen=True)
class StructureBreak:
    index: int
    swing_index: int
    direction: BreakSide
    kind: BreakKind
    level: Decimal
    close: Decimal


@dataclass(frozen=True)
class OrderBlock:
    direction: BreakSide
    candle_index: int
    break_index: int
    zone_lower: Decimal
    zone_upper: Decimal
    body_lower: Decimal
    body_upper: Decimal
    invalidation: Decimal
    contract_code: str | None


def find_breaks(
    prepared: PreparedSeries, swings: list[Swing], tick: Decimal
) -> list[StructureBreak]:
    consumed: set[int] = set()
    found: list[StructureBreak] = []
    bars = prepared.bars
    for index, bar in enumerate(bars):
        structure = _structure(swings, bars, index)
        high = _latest_swing(swings, bars, index, consumed, want_high=True)
        low = _latest_swing(swings, bars, index, consumed, want_high=False)
        broke_high = high is not None and bar.close >= bars[high.index].high + tick
        broke_low = low is not None and bar.close <= bars[low.index].low - tick
        if broke_high and broke_low:
            continue
        if broke_high and high is not None:
            consumed.add(high.index)
            found.append(_break(index, high, "bullish", structure, bars))
        elif broke_low and low is not None:
            consumed.add(low.index)
            found.append(_break(index, low, "bearish", structure, bars))
    return found


def find_order_blocks(
    prepared: PreparedSeries,
    breaks: list[StructureBreak],
    atr: dict[int, Decimal],
    *,
    body_ratio: Decimal,
    lookback: int,
    use_body: bool,
) -> tuple[list[OrderBlock], bool]:
    """Return blocks and whether any break was skipped because ATR was not ready."""
    if lookback < 1:
        msg = "order block lookback must be positive"
        raise ValueError(msg)
    used: set[int] = set()
    blocks: list[OrderBlock] = []
    skipped_atr = False
    for item in breaks:
        preceding = atr.get(item.index - 1)
        if not _displaced(prepared.bars[item.index], preceding, body_ratio):
            if preceding is None:
                skipped_atr = True
            continue
        candle = _opposite_candle(prepared, item.index, item.direction, lookback)
        if candle is None or candle in used:
            continue
        used.add(candle)
        blocks.append(_block(prepared.bars, candle, item, use_body))
    return blocks, skipped_atr


def track_order_block(
    prepared: PreparedSeries, block: OrderBlock
) -> tuple[FeatureState, list[TransitionDraft]]:
    state: FeatureState = "confirmed"
    transitions: list[TransitionDraft] = []
    traversed = False
    bars = prepared.bars
    for index in range(block.break_index + 1, len(bars)):
        if bars[index].contract_code != block.contract_code:
            break
        if prepared.gaps[index - 1] in {"roll", "missing"}:
            break
        bar = bars[index]
        revisits = bar.low <= block.zone_upper and bar.high >= block.zone_lower
        covers = bar.low <= block.zone_lower and bar.high >= block.zone_upper
        failed = _invalid(block, bar)
        if revisits and not _seen(transitions, "revisited"):
            transitions.append(_transition(state, "revisited", bar, covers))
            state = "revisited"
        if covers:
            traversed = True
        if failed and not _seen(transitions, "invalidated"):
            transitions.append(_transition(state, "invalidated", bar, covers or traversed))
            state = "invalidated"
            break
    return state, transitions


def _break(
    index: int, swing: Swing, direction: BreakSide, structure: str, bars: tuple[Bar, ...]
) -> StructureBreak:
    level = bars[swing.index].high if direction == "bullish" else bars[swing.index].low
    kind: BreakKind
    if structure == "unknown":
        kind = "unknown"
    elif (direction == "bullish" and structure == "bullish") or (
        direction == "bearish" and structure == "bearish"
    ):
        kind = "continuation"
    else:
        kind = "structure_change"
    return StructureBreak(
        index=index,
        swing_index=swing.index,
        direction=direction,
        kind=kind,
        level=level,
        close=bars[index].close,
    )


def _structure(swings: list[Swing], bars: tuple[Bar, ...], before: int) -> str:
    known = [swing for swing in swings if swing.confirmation_index < before]
    highs = [swing for swing in known if swing.is_high]
    lows = [swing for swing in known if swing.is_low]
    if len(highs) < 2 or len(lows) < 2:
        return "unknown"
    earlier_high = bars[highs[-2].index].high
    later_high = bars[highs[-1].index].high
    earlier_low = bars[lows[-2].index].low
    later_low = bars[lows[-1].index].low
    if later_high > earlier_high and later_low > earlier_low:
        return "bullish"
    if later_high < earlier_high and later_low < earlier_low:
        return "bearish"
    return "unknown"


def _latest_swing(
    swings: list[Swing],
    bars: tuple[Bar, ...],
    index: int,
    consumed: set[int],
    *,
    want_high: bool,
) -> Swing | None:
    bar = bars[index]
    candidates = [
        swing
        for swing in swings
        if swing.confirmation_index < index
        and swing.index not in consumed
        and swing.contract_code == bar.contract_code
        and (swing.is_high if want_high else swing.is_low)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda swing: swing.index)


def _displaced(bar: Bar, preceding_atr: Decimal | None, body_ratio: Decimal) -> bool:
    if preceding_atr is None:
        return False
    span = bar.high - bar.low
    if span == 0:
        return False
    body = abs(bar.close - bar.open)
    return body >= preceding_atr and (body / span) >= body_ratio


def _opposite_candle(
    prepared: PreparedSeries, break_index: int, direction: BreakSide, lookback: int
) -> int | None:
    checked = 0
    index = break_index - 1
    break_contract = prepared.bars[break_index].contract_code
    while index >= 0 and checked < lookback:
        if prepared.gaps[index] != "ok":
            return None
        bar = prepared.bars[index]
        if bar.contract_code != break_contract:
            return None
        checked += 1
        if direction == "bullish" and bar.close < bar.open:
            return index
        if direction == "bearish" and bar.close > bar.open:
            return index
        index -= 1
    return None


def _block(bars: tuple[Bar, ...], candle: int, item: StructureBreak, use_body: bool) -> OrderBlock:
    bar = bars[candle]
    body_lower = min(bar.open, bar.close)
    body_upper = max(bar.open, bar.close)
    if use_body:
        zone_lower, zone_upper = body_lower, body_upper
    else:
        zone_lower, zone_upper = bar.low, bar.high
    invalidation = bar.low if item.direction == "bullish" else bar.high
    return OrderBlock(
        direction=item.direction,
        candle_index=candle,
        break_index=item.index,
        zone_lower=zone_lower,
        zone_upper=zone_upper,
        body_lower=body_lower,
        body_upper=body_upper,
        invalidation=invalidation,
        contract_code=bar.contract_code,
    )


def _invalid(block: OrderBlock, bar: Bar) -> bool:
    if block.direction == "bullish":
        return bar.close < block.invalidation
    return bar.close > block.invalidation


def _seen(transitions: list[TransitionDraft], target: FeatureState) -> bool:
    return any(item.to_state == target for item in transitions)


def _transition(
    state: FeatureState, target: FeatureState, bar: Bar, traversed: bool
) -> TransitionDraft:
    details: dict[str, JsonValue] = {"traversed": traversed}
    return TransitionDraft(
        from_state=state,
        to_state=target,
        bar_time=bar_close_time(bar),
        bar_tz=bar.origin_tz,
        details=details,
    )


def break_details(item: StructureBreak) -> dict[str, JsonValue]:
    return {
        "break_index": item.index,
        "swing_index": item.swing_index,
        "kind": item.kind,
        "level": decimal_str(item.level),
        "close": decimal_str(item.close),
    }
