"""Regular RSI divergence, with hidden divergence available as a separate optional pass.

Compare consecutive confirmed pivots of the same kind. Bullish regular divergence is a
lower low in price and a higher RSI; bearish regular divergence is a higher high and a
lower RSI. Hidden bullish is a higher low and a lower RSI; hidden bearish is a lower high
and a higher RSI. Defaults: pivots 5 to 60 bars apart, price difference at least one tick,
RSI difference at least 2 points. The event is emitted when the second pivot confirms.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from trading_core.ta.envelope import decimal_str

if TYPE_CHECKING:
    from decimal import Decimal

    from pydantic import JsonValue

    from trading_core.domain.common import Direction
    from trading_core.ta.series import PreparedSeries
    from trading_core.ta.swings import Swing

Kind = Literal["regular", "hidden"]


@dataclass(frozen=True)
class Divergence:
    direction: Direction
    kind: Kind
    first_index: int
    second_index: int
    price_first: Decimal
    price_second: Decimal
    rsi_first: Decimal
    rsi_second: Decimal
    contract_code: str | None
    confirmation_index: int


def find_divergences(
    prepared: PreparedSeries,
    swings: list[Swing],
    rsi: dict[int, Decimal],
    *,
    min_separation: int,
    max_separation: int,
    min_points: Decimal,
    include_hidden: bool,
) -> list[Divergence]:
    if min_separation < 1 or max_separation < min_separation:
        msg = "RSI divergence separation bounds are invalid"
        raise ValueError(msg)
    found: list[Divergence] = []
    found.extend(
        _pairs(
            prepared,
            [swing for swing in swings if swing.is_low],
            rsi,
            want_low=True,
            min_separation=min_separation,
            max_separation=max_separation,
            min_points=min_points,
            include_hidden=include_hidden,
        )
    )
    found.extend(
        _pairs(
            prepared,
            [swing for swing in swings if swing.is_high],
            rsi,
            want_low=False,
            min_separation=min_separation,
            max_separation=max_separation,
            min_points=min_points,
            include_hidden=include_hidden,
        )
    )
    found.sort(key=lambda item: (item.confirmation_index, item.second_index, item.direction))
    return found


def divergence_details(item: Divergence) -> dict[str, JsonValue]:
    return {
        "kind": item.kind,
        "first_index": item.first_index,
        "second_index": item.second_index,
        "price_first": decimal_str(item.price_first),
        "price_second": decimal_str(item.price_second),
        "rsi_first": decimal_str(item.rsi_first),
        "rsi_second": decimal_str(item.rsi_second),
    }


def _pairs(
    prepared: PreparedSeries,
    pivots: list[Swing],
    rsi: dict[int, Decimal],
    *,
    want_low: bool,
    min_separation: int,
    max_separation: int,
    min_points: Decimal,
    include_hidden: bool,
) -> list[Divergence]:
    found: list[Divergence] = []
    bars = prepared.bars
    for earlier, later in itertools.pairwise(pivots):
        separation = later.index - earlier.index
        if separation < min_separation or separation > max_separation:
            continue
        if earlier.contract_code != later.contract_code:
            continue
        if _blocked(prepared, earlier.index, later.index):
            continue
        if earlier.index not in rsi or later.index not in rsi:
            continue
        first_price = bars[earlier.index].low if want_low else bars[earlier.index].high
        second_price = bars[later.index].low if want_low else bars[later.index].high
        if abs(second_price - first_price) < prepared.tick:
            continue
        first_rsi = rsi[earlier.index]
        second_rsi = rsi[later.index]
        if abs(second_rsi - first_rsi) < min_points:
            continue
        kind = _classify(want_low, first_price, second_price, first_rsi, second_rsi, include_hidden)
        if kind is None:
            continue
        direction: Direction = "bullish" if want_low else "bearish"
        found.append(
            Divergence(
                direction=direction,
                kind=kind[0],
                first_index=earlier.index,
                second_index=later.index,
                price_first=first_price,
                price_second=second_price,
                rsi_first=first_rsi,
                rsi_second=second_rsi,
                contract_code=later.contract_code,
                confirmation_index=later.confirmation_index,
            )
        )
    return found


def _blocked(prepared: PreparedSeries, start: int, end: int) -> bool:
    return any(prepared.gaps[index] in {"missing", "roll"} for index in range(start, end))


def _classify(
    want_low: bool,
    first_price: Decimal,
    second_price: Decimal,
    first_rsi: Decimal,
    second_rsi: Decimal,
    include_hidden: bool,
) -> tuple[Kind] | None:
    if want_low and second_price < first_price and second_rsi > first_rsi:
        return ("regular",)
    if not want_low and second_price > first_price and second_rsi < first_rsi:
        return ("regular",)
    if not include_hidden:
        return None
    if want_low and second_price > first_price and second_rsi < first_rsi:
        return ("hidden",)
    if not want_low and second_price < first_price and second_rsi > first_rsi:
        return ("hidden",)
    return None
