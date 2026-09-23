"""Strict swing pivots and equal-extreme liquidity pools.

A swing at index ``i`` uses three bars on each side and strict inequality. It is not knowable
until bar ``i + 3`` has closed, and the six neighbouring gaps must be ordinary one-bar steps
(no session break, missing bar, or roll inside the wing).

Equal extrema are not pivots. They form a liquidity pool: at least two touches, first-to-last
index separation of at least three bars, and a price span of at most two ticks. A pool freezes
when it first qualifies so a later bar cannot rewrite it. High and low pools are allocated
origin bars in confirmation order; the preferred origin is the first touch, and a later pool
that would reuse that timestamp takes its next member bar instead. That keeps the Stage 0
event key unique without a new column.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from trading_core.ta.constants import (
    PIVOT_WING,
    POOL_MAX_SPAN_TICKS,
    POOL_MIN_SEPARATION,
    POOL_MIN_TOUCHES,
)
from trading_core.ta.series import PreparedSeries, bar_close_time

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from trading_core.domain.market import Bar

Side = Literal["high", "low"]


@dataclass(frozen=True)
class Swing:
    index: int
    is_high: bool
    is_low: bool
    origin_time: datetime
    origin_tz: str
    confirmation_time: datetime
    confirmation_index: int
    contract_code: str | None


@dataclass(frozen=True)
class Pool:
    side: Side
    members: tuple[int, ...]
    level: Decimal
    formed_index: int
    confirmation_index: int
    origin_index: int
    origin_adjusted: bool
    contract_code: str | None


def detect_swings(prepared: PreparedSeries, wing: int = PIVOT_WING) -> list[Swing]:
    bars = prepared.bars
    found: list[Swing] = []
    if len(bars) < (wing * 2) + 1:
        return found
    for index in range(wing, len(bars) - wing):
        if not prepared.consecutive(index - wing, index + wing):
            continue
        is_high = _is_strict_high(bars, index, wing)
        is_low = _is_strict_low(bars, index, wing)
        if not is_high and not is_low:
            continue
        confirm_at = index + wing
        found.append(
            Swing(
                index=index,
                is_high=is_high,
                is_low=is_low,
                origin_time=bars[index].origin_time,
                origin_tz=bars[index].origin_tz,
                confirmation_time=bar_close_time(bars[confirm_at]),
                confirmation_index=confirm_at,
                contract_code=bars[index].contract_code,
            )
        )
    return found


def detect_pools(prepared: PreparedSeries, tick: Decimal) -> list[Pool]:
    span = tick * POOL_MAX_SPAN_TICKS
    highs = _scan_side(prepared, "high", span)
    lows = _scan_side(prepared, "low", span)
    return _allocate_origins(highs + lows)


def _is_strict_high(bars: tuple[Bar, ...], index: int, wing: int) -> bool:
    price = bars[index].high
    neighbors = range(-wing, wing + 1)
    return all(price > bars[index + offset].high for offset in neighbors if offset != 0)


def _is_strict_low(bars: tuple[Bar, ...], index: int, wing: int) -> bool:
    price = bars[index].low
    neighbors = range(-wing, wing + 1)
    return all(price < bars[index + offset].low for offset in neighbors if offset != 0)


@dataclass
class _Cluster:
    side: Side
    members: list[int]
    min_price: Decimal
    max_price: Decimal
    confirmed: bool
    contract_code: str | None


def _scan_side(prepared: PreparedSeries, side: Side, max_span: Decimal) -> list[Pool]:
    clusters: list[_Cluster] = []
    pools: list[Pool] = []
    for index, bar in enumerate(prepared.bars):
        if index > 0 and prepared.gaps[index - 1] in {"roll", "missing"}:
            clusters = []
        price = bar.high if side == "high" else bar.low
        if _revisit(clusters, price, max_span):
            continue
        cluster = _extend(clusters, side, index, price, max_span, bar.contract_code)
        if cluster is None:
            clusters.append(
                _Cluster(
                    side=side,
                    members=[index],
                    min_price=price,
                    max_price=price,
                    confirmed=False,
                    contract_code=bar.contract_code,
                )
            )
            continue
        if not cluster.confirmed and _qualifies(cluster):
            cluster.confirmed = True
            pools.append(_freeze(cluster))
    return pools


def _revisit(clusters: list[_Cluster], price: Decimal, max_span: Decimal) -> bool:
    for cluster in clusters:
        if not cluster.confirmed:
            continue
        if _fits(cluster, price, max_span):
            return True
    return False


def _extend(
    clusters: list[_Cluster],
    side: Side,
    index: int,
    price: Decimal,
    max_span: Decimal,
    contract_code: str | None,
) -> _Cluster | None:
    for cluster in clusters:
        if cluster.confirmed or cluster.side != side:
            continue
        if cluster.contract_code != contract_code:
            continue
        if not _fits(cluster, price, max_span):
            continue
        cluster.members.append(index)
        cluster.min_price = min(cluster.min_price, price)
        cluster.max_price = max(cluster.max_price, price)
        return cluster
    return None


def _fits(cluster: _Cluster, price: Decimal, max_span: Decimal) -> bool:
    return max(cluster.max_price, price) - min(cluster.min_price, price) <= max_span


def _qualifies(cluster: _Cluster) -> bool:
    if len(cluster.members) < POOL_MIN_TOUCHES:
        return False
    return cluster.members[-1] - cluster.members[0] >= POOL_MIN_SEPARATION


def _freeze(cluster: _Cluster) -> Pool:
    level = cluster.max_price if cluster.side == "high" else cluster.min_price
    members = tuple(cluster.members)
    return Pool(
        side=cluster.side,
        members=members,
        level=level,
        formed_index=members[0],
        confirmation_index=members[-1],
        origin_index=members[0],
        origin_adjusted=False,
        contract_code=cluster.contract_code,
    )


def _allocate_origins(pools: list[Pool]) -> list[Pool]:
    """Prefix-stable origin indexes. Earlier-confirmed pools keep the bar they already took."""
    order = sorted(
        range(len(pools)),
        key=lambda item: (
            pools[item].confirmation_index,
            pools[item].side,
            pools[item].formed_index,
        ),
    )
    used: set[int] = set()
    assigned: list[Pool] = list(pools)
    for position in order:
        pool = pools[position]
        chosen = _first_free(pool.members, used)
        if chosen is None:
            msg = (
                "liquidity pools need a level discriminator on ta_events; "
                "member bars were not enough to keep origin times unique"
            )
            raise RuntimeError(msg)
        used.add(chosen)
        assigned[position] = Pool(
            side=pool.side,
            members=pool.members,
            level=pool.level,
            formed_index=pool.formed_index,
            confirmation_index=pool.confirmation_index,
            origin_index=chosen,
            origin_adjusted=chosen != pool.formed_index,
            contract_code=pool.contract_code,
        )
    return assigned


def _first_free(members: tuple[int, ...], used: set[int]) -> int | None:
    for index in members:
        if index not in used:
            return index
    return None
