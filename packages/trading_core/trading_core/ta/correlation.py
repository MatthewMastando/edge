"""Pearson correlation of aligned bar-to-bar returns.

A return is aligned only when both series step from the same previous timestamp to the
same current timestamp. Sample correlation (divisor n - 1) is used. A flat series has
undefined correlation and is rejected rather than reported as zero.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from trading_core.ta.constants import MIN_ALIGNED_RETURNS
from trading_core.ta.interfaces import InsufficientDataError

if TYPE_CHECKING:
    from datetime import datetime


def aligned_return_correlation(
    left: list[tuple[datetime, Decimal]],
    right: list[tuple[datetime, Decimal]],
) -> tuple[Decimal, int]:
    left_closes = _unique(left, "left")
    right_closes = _unique(right, "right")
    left_prev = _previous(left_closes)
    right_prev = _previous(right_closes)
    xs: list[Decimal] = []
    ys: list[Decimal] = []
    for instant in sorted(set(left_closes) & set(right_closes)):
        if instant not in left_prev or instant not in right_prev:
            continue
        if left_prev[instant] != right_prev[instant]:
            continue
        previous_left = left_closes[left_prev[instant]]
        previous_right = right_closes[right_prev[instant]]
        if previous_left == 0 or previous_right == 0:
            msg = "correlation return is undefined at a zero close"
            raise InsufficientDataError(msg)
        xs.append((left_closes[instant] - previous_left) / previous_left)
        ys.append((right_closes[instant] - previous_right) / previous_right)
    return _pearson(xs, ys), len(xs)


def _unique(series: list[tuple[datetime, Decimal]], label: str) -> dict[datetime, Decimal]:
    found: dict[datetime, Decimal] = {}
    for instant, close in series:
        if instant in found:
            msg = f"duplicate {label} bar at {instant.isoformat()}"
            raise InsufficientDataError(msg)
        found[instant] = close
    return found


def _previous(closes: dict[datetime, Decimal]) -> dict[datetime, datetime]:
    ordered = sorted(closes)
    return {current: ordered[index - 1] for index, current in enumerate(ordered) if index > 0}


def _pearson(xs: list[Decimal], ys: list[Decimal]) -> Decimal:
    count = len(xs)
    if count < MIN_ALIGNED_RETURNS:
        msg = f"correlation needs {MIN_ALIGNED_RETURNS} aligned returns; got {count}"
        raise InsufficientDataError(msg)
    mean_x = sum(xs, start=Decimal(0)) / Decimal(count)
    mean_y = sum(ys, start=Decimal(0)) / Decimal(count)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    if variance_x == 0 or variance_y == 0:
        msg = "correlation is undefined for a flat return series"
        raise InsufficientDataError(msg)
    # Population sums cancel the shared (n - 1) divisor.
    scale = covariance / (variance_x.sqrt() * variance_y.sqrt())
    if scale > 1:
        return Decimal(1)
    if scale < -1:
        return Decimal(-1)
    return scale
