"""Tick-aligned volume profile.

Value area starts at the POC and repeatedly adds the larger adjacent bin until covered volume
is at least 70 percent. POC ties take the lower price. Expansion ties take the bin closer to
the POC, then the lower price.

Nodes use a 3-bin moving average. A local extremum is the middle of a plateau (the lower
middle when the plateau length is even) whose ±2 neighbourhood is strictly beyond it.
Percentiles are the linear (Hyndman-Fan type 7) percentiles of the smoothed values on bins
where that smoothed value is not zero. HVN is a local maximum at or above the 75th; LVN is
a local minimum at or below the 25th. When those two percentiles are equal, no nodes are
emitted.

Trade size is binned at the print price. Aggressor side is ignored. Bars alone never become
exact volume: the caller must opt into a labeled uniform range approximation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from trading_core.ta.calendar import expected_origins, locate_session, rth_bounds, trading_bounds
from trading_core.ta.constants import (
    NODE_EXTREMUM_WING,
    NODE_HVN_PERCENTILE,
    NODE_LVN_PERCENTILE,
    NODE_MA_BINS,
    VALUE_AREA_FRACTION,
)
from trading_core.ta.interfaces import InsufficientDataError
from trading_core.ta.series import PreparedSeries, bar_close_time, bar_step, is_tick_aligned
from trading_core.ta.session_levels import session_has_overnight

if TYPE_CHECKING:
    from datetime import date, datetime, timedelta

    from trading_core.domain.instruments import SessionCalendar
    from trading_core.domain.market import Bar, Trade

Source = Literal["trades", "bar_range_approximation"]
CoverageKind = Literal["full", "prefix", "censored", "empty"]


@dataclass(frozen=True)
class ProfileWindow:
    start: datetime
    end: datetime
    origin_time: datetime
    confirmation_time: datetime | None
    complete: bool
    contract_code: str | None
    session_day: date | None
    bar_indexes: tuple[int, ...]


@dataclass(frozen=True)
class VolumeProfile:
    window: ProfileWindow
    prices: tuple[Decimal, ...]
    volumes: tuple[Decimal, ...]
    poc: Decimal
    vah: Decimal
    val: Decimal
    covered: Decimal
    total: Decimal
    hvn: tuple[Decimal, ...]
    lvn: tuple[Decimal, ...]
    p25: Decimal | None
    p75: Decimal | None
    source: Source


def build_profile(
    prices: list[Decimal], volumes: list[Decimal], window: ProfileWindow, source: Source
) -> VolumeProfile:
    if len(prices) != len(volumes) or not prices:
        msg = "volume profile histogram is empty"
        raise InsufficientDataError(msg)
    total = sum(volumes, start=Decimal(0))
    if total <= 0:
        msg = "volume profile has no volume in the window"
        raise InsufficientDataError(msg)
    poc_index = _poc_index(volumes)
    val_index, vah_index, covered = _value_area(volumes, poc_index, total * VALUE_AREA_FRACTION)
    hvn_idx, lvn_idx, p25, p75 = _nodes(volumes)
    return VolumeProfile(
        window=window,
        prices=tuple(prices),
        volumes=tuple(volumes),
        poc=prices[poc_index],
        vah=prices[vah_index],
        val=prices[val_index],
        covered=covered,
        total=total,
        hvn=tuple(prices[index] for index in hvn_idx),
        lvn=tuple(prices[index] for index in lvn_idx),
        p25=p25,
        p75=p75,
        source=source,
    )


def histogram_from_trades(
    trades: list[Trade], tick: Decimal
) -> tuple[list[Decimal], list[Decimal]]:
    buckets: dict[Decimal, Decimal] = {}
    for trade in trades:
        if trade.size < 0:
            msg = "trade size is negative"
            raise ValueError(msg)
        if not is_tick_aligned(trade.price, tick):
            msg = f"trade {trade.trade_time.isoformat()} is not tick-aligned"
            raise InsufficientDataError(msg)
        if trade.size == 0:
            continue
        buckets[trade.price] = buckets.get(trade.price, Decimal(0)) + trade.size
    return _materialize(buckets, tick)


def histogram_from_bars(bars: list[Bar], tick: Decimal) -> tuple[list[Decimal], list[Decimal]]:
    buckets: dict[Decimal, Decimal] = {}
    for bar in bars:
        if bar.volume == 0:
            continue
        if not is_tick_aligned(bar.low, tick) or not is_tick_aligned(bar.high, tick):
            msg = f"bar {bar.origin_time.isoformat()} is not tick-aligned"
            raise InsufficientDataError(msg)
        count = int((bar.high - bar.low) / tick) + 1
        for offset, part in enumerate(split_even(bar.volume, count)):
            price = bar.low + (tick * offset)
            buckets[price] = buckets.get(price, Decimal(0)) + part
    return _materialize(buckets, tick)


def split_even(volume: Decimal, count: int) -> list[Decimal]:
    """Split ``volume`` into ``count`` parts that sum exactly. Extra quanta go to lower prices."""
    if count < 1:
        msg = "cannot split volume across zero bins"
        raise ValueError(msg)
    exponent = volume.as_tuple().exponent
    if not isinstance(exponent, int):
        msg = "volume is not finite"
        raise ValueError(msg)
    if exponent >= 0:
        quantum = Decimal(1)
        scaled = int(volume)
    else:
        quantum = Decimal(10) ** exponent
        scaled = int((volume / quantum).to_integral_value())
    base, remainder = divmod(scaled, count)
    return [Decimal(base + (1 if index < remainder else 0)) * quantum for index in range(count)]


def trades_for_bars(bars: list[Bar], trades: list[Trade]) -> list[Trade]:
    """Prints inside completed bars only. A later print with no bar is not profile volume."""
    if not bars:
        return []
    step = bar_step(bars[0].timeframe)
    selected: list[Trade] = []
    for trade in trades:
        if trade.size < 0:
            msg = "trade size is negative"
            raise ValueError(msg)
        for bar in bars:
            if bar.contract_code is not None and trade.contract_code != bar.contract_code:
                continue
            close = bar.origin_time + step
            if bar.origin_time <= trade.trade_time < close:
                selected.append(trade)
                break
    return selected


def trade_coverage_matches(bars: list[Bar], trades: list[Trade]) -> bool:
    """True when positive bar volume equals in-bar print size and some size was printed."""
    if not bars:
        return False
    step = bar_step(bars[0].timeframe)
    saw_size = False
    for bar in bars:
        traded = _size_in_bar(bar, trades, step)
        if bar.volume > 0 and traded != bar.volume:
            return False
        if traded > 0:
            saw_size = True
    return saw_size


def assert_trade_coverage(bars: list[Bar], trades: list[Trade]) -> None:
    """A shortfall against bar volume is missing coverage, not zero volume."""
    if not bars:
        return
    step = bar_step(bars[0].timeframe)
    for bar in bars:
        if bar.volume <= 0:
            continue
        traded = _size_in_bar(bar, trades, step)
        if traded != bar.volume:
            msg = (
                f"bar {bar.origin_time.isoformat()} volume is {format(bar.volume, 'f')} "
                f"but in-bar trade size sums to {format(traded, 'f')}; "
                "missing coverage is not zero volume"
            )
            raise InsufficientDataError(msg)


def _size_in_bar(bar: Bar, trades: list[Trade], step: timedelta) -> Decimal:
    close = bar.origin_time + step
    total = Decimal(0)
    for trade in trades:
        if trade.size < 0:
            msg = "trade size is negative"
            raise ValueError(msg)
        if bar.contract_code is not None and trade.contract_code != bar.contract_code:
            continue
        if bar.origin_time <= trade.trade_time < close:
            total += trade.size
    return total


def select_windows(
    prepared: PreparedSeries,
    calendar: SessionCalendar,
    scope: str,
    *,
    session_count: int,
    anchor_time: datetime | None,
    end_time: datetime | None,
    range_start: datetime | None,
    range_end: datetime | None,
) -> list[ProfileWindow]:
    if scope == "anchored":
        return [_anchored_window(prepared, anchor_time, end_time)]
    if scope == "fixed_range":
        return [_fixed_window(prepared, range_start, range_end)]
    if scope == "composite":
        return _composite_windows(prepared, calendar, session_count)
    return _scoped_windows(prepared, calendar, scope)


def percentile_linear(sorted_values: list[Decimal], probability: Decimal) -> Decimal:
    """Hyndman-Fan type 7 (NumPy's linear percentile), in Decimal."""
    count = len(sorted_values)
    if count == 0:
        msg = "percentile of an empty sample"
        raise ValueError(msg)
    if count == 1:
        return sorted_values[0]
    position = Decimal(count - 1) * probability
    lower = int(position)
    upper = min(lower + 1, count - 1)
    fraction = position - Decimal(lower)
    return (sorted_values[lower] * (Decimal(1) - fraction)) + (sorted_values[upper] * fraction)


def _materialize(
    buckets: dict[Decimal, Decimal], tick: Decimal
) -> tuple[list[Decimal], list[Decimal]]:
    if not buckets:
        msg = "no trade size in the profile window"
        raise InsufficientDataError(msg)
    low = min(buckets)
    high = max(buckets)
    steps = int((high - low) / tick)
    prices = [low + (tick * step) for step in range(steps + 1)]
    volumes = [buckets.get(price, Decimal(0)) for price in prices]
    return prices, volumes


def _poc_index(volumes: list[Decimal]) -> int:
    chosen = 0
    for index, volume in enumerate(volumes):
        if volume > volumes[chosen]:
            chosen = index
    return chosen


def _value_area(volumes: list[Decimal], poc: int, target: Decimal) -> tuple[int, int, Decimal]:
    low = poc
    high = poc
    covered = volumes[poc]
    count = len(volumes)
    while covered < target and (low > 0 or high < count - 1):
        below = low - 1 if low > 0 else None
        above = high + 1 if high < count - 1 else None
        choice = _expansion_side(below, above, volumes, poc)
        if choice is None:
            break
        if choice < poc:
            low = choice
        else:
            high = choice
        covered += volumes[choice]
    return low, high, covered


def _expansion_side(
    below: int | None, above: int | None, volumes: list[Decimal], poc: int
) -> int | None:
    if below is None and above is None:
        return None
    if below is None:
        return above
    if above is None:
        return below
    below_volume = volumes[below]
    above_volume = volumes[above]
    if below_volume != above_volume:
        return below if below_volume > above_volume else above
    # Equal volume: the closer bin, then the lower price.
    if (poc - below) <= (above - poc):
        return below
    return above


def _nodes(volumes: list[Decimal]) -> tuple[list[int], list[int], Decimal | None, Decimal | None]:
    count = len(volumes)
    if count < NODE_MA_BINS:
        return [], [], None, None
    half = NODE_MA_BINS // 2
    smoothed: list[Decimal | None] = [None] * count
    for index in range(half, count - half):
        window = volumes[index - half : index + half + 1]
        smoothed[index] = sum(window, start=Decimal(0)) / Decimal(NODE_MA_BINS)
    samples = sorted(value for value in smoothed if value is not None and value != 0)
    if not samples:
        return [], [], None, None
    p25 = percentile_linear(samples, NODE_LVN_PERCENTILE)
    p75 = percentile_linear(samples, NODE_HVN_PERCENTILE)
    if p25 == p75:
        return [], [], p25, p75
    return (
        _extrema(smoothed, kind="max", threshold=p75),
        _extrema(smoothed, kind="min", threshold=p25),
        p25,
        p75,
    )


def _extrema(smoothed: list[Decimal | None], *, kind: str, threshold: Decimal) -> list[int]:
    found: list[int] = []
    index = 1
    last = len(smoothed) - 1
    while index < last:
        if smoothed[index] is None:
            index += 1
            continue
        end = index
        while end + 1 < last and smoothed[end + 1] == smoothed[index]:
            end += 1
        middle = index + ((end - index) // 2)
        if _is_local_extremum(smoothed, middle, kind):
            value = smoothed[middle]
            if value is not None and _passes(value, threshold, kind):
                found.append(middle)
        index = end + 1
    return found


def _passes(value: Decimal, threshold: Decimal, kind: str) -> bool:
    if kind == "max":
        return value >= threshold
    return value <= threshold


def _is_local_extremum(smoothed: list[Decimal | None], middle: int, kind: str) -> bool:
    """Strict against bins within ±wing of the plateau middle. Equal bins are the plateau tie."""
    value = smoothed[middle]
    if value is None:
        return False
    strict: list[Decimal] = []
    start = middle - NODE_EXTREMUM_WING
    stop = middle + NODE_EXTREMUM_WING
    for offset in range(start, stop + 1):
        if offset == middle:
            continue
        if offset < 0 or offset >= len(smoothed):
            return False
        neighbor = smoothed[offset]
        if neighbor is None:
            return False
        if neighbor == value:
            continue
        strict.append(neighbor)
    if not strict:
        return False
    if kind == "max":
        return all(item < value for item in strict)
    return all(item > value for item in strict)


def _scoped_windows(
    prepared: PreparedSeries, calendar: SessionCalendar, scope: str
) -> list[ProfileWindow]:
    groups = _groups(prepared, calendar)
    if not groups:
        msg = "no session windows in the series"
        raise InsufficientDataError(msg)
    windows: list[ProfileWindow] = []
    for position, (session_day, indexes) in enumerate(groups):
        is_last = position == len(groups) - 1
        is_first = position == 0
        if scope == "prior_session" and is_last:
            continue
        # A session becomes "prior" when the next session's first bar closes. Logging it at
        # the prior session's own close would be a back-dated event on that later bar.
        prior_confirm = None
        if scope == "prior_session":
            next_indexes = groups[position + 1][1]
            prior_confirm = bar_close_time(prepared.bars[next_indexes[0]])
        if scope == "eth":
            eth_window = _eth_window(
                prepared, calendar, session_day, indexes, is_first=is_first, is_last=is_last
            )
            if eth_window is not None:
                windows.append(eth_window)
            continue
        bounds = _scope_bounds(calendar, session_day, indexes, prepared, scope)
        for start, end, indexes_in in bounds:
            coverage = _classify(
                prepared, indexes_in, start, end, is_first=is_first, is_last=is_last
            )
            if coverage in {"empty", "censored"}:
                continue
            if coverage == "prefix" and not is_last:
                msg = "missing bar inside a profile window"
                raise InsufficientDataError(msg)
            windows.append(
                _window_from_indexes(
                    prepared,
                    indexes_in,
                    start,
                    end,
                    session_day,
                    coverage,
                    confirm_at=prior_confirm,
                )
            )
    if not windows:
        msg = f"no {scope} window with usable coverage"
        raise InsufficientDataError(msg)
    return windows


def _scope_bounds(
    calendar: SessionCalendar,
    session_day: date,
    indexes: list[int],
    prepared: PreparedSeries,
    scope: str,
) -> list[tuple[datetime, datetime, list[int]]]:
    trading = trading_bounds(calendar, session_day)
    if len(trading) != 1:
        msg = f"session {session_day.isoformat()} does not have one trading window"
        raise ValueError(msg)
    opens, closes = trading[0]
    rth = rth_bounds(calendar, session_day)
    if scope in {"current_session", "prior_session"}:
        return [(opens, closes, _inside(prepared, indexes, opens, closes))]
    if scope == "rth":
        if rth is None:
            return [(opens, closes, _inside(prepared, indexes, opens, closes))]
        return [(rth[0], rth[1], _inside(prepared, indexes, rth[0], rth[1]))]
    if scope == "overnight":
        if rth is None:
            msg = "overnight profile requires an RTH sub-session on the calendar"
            raise InsufficientDataError(msg)
        return [(opens, rth[0], _inside(prepared, indexes, opens, rth[0]))]
    msg = f"unsupported volume-profile session scope {scope!r}"
    raise ValueError(msg)


def _composite_windows(
    prepared: PreparedSeries, calendar: SessionCalendar, session_count: int
) -> list[ProfileWindow]:
    if session_count < 1:
        msg = "session_count must be positive"
        raise ValueError(msg)
    groups = _groups(prepared, calendar)
    completed: list[tuple[date, list[int], datetime, datetime]] = []
    last_position = len(groups) - 1
    for position, (session_day, indexes) in enumerate(groups):
        trading = trading_bounds(calendar, session_day)
        if len(trading) != 1:
            continue
        opens, closes = trading[0]
        inside = _inside(prepared, indexes, opens, closes)
        coverage = _classify(
            prepared,
            inside,
            opens,
            closes,
            is_first=position == 0,
            is_last=position == last_position,
        )
        if coverage == "full":
            completed.append((session_day, inside, opens, closes))
    if len(completed) < session_count:
        msg = f"composite profile needs {session_count} completed sessions"
        raise InsufficientDataError(msg)
    windows: list[ProfileWindow] = []
    for end in range(session_count, len(completed) + 1):
        chunk = completed[end - session_count : end]
        indexes = [index for _day, bars, _open, _close in chunk for index in bars]
        start = chunk[0][2]
        stop = chunk[-1][3]
        windows.append(_window_from_indexes(prepared, indexes, start, stop, chunk[0][0], "full"))
    return windows


def _anchored_window(
    prepared: PreparedSeries, anchor_time: datetime | None, end_time: datetime | None
) -> ProfileWindow:
    if anchor_time is None:
        msg = "anchored profile requires anchor_time"
        raise ValueError(msg)
    return _range_window(prepared, anchor_time, end_time, require_end=False)


def _fixed_window(
    prepared: PreparedSeries, range_start: datetime | None, range_end: datetime | None
) -> ProfileWindow:
    if range_start is None or range_end is None:
        msg = "fixed_range profile requires range_start and range_end"
        raise ValueError(msg)
    if range_end <= range_start:
        msg = "fixed_range end must be after the start"
        raise ValueError(msg)
    return _range_window(prepared, range_start, range_end, require_end=True)


def _range_window(
    prepared: PreparedSeries, start: datetime, end: datetime | None, *, require_end: bool
) -> ProfileWindow:
    last_close = bar_close_time(prepared.bars[-1])
    stop = end if end is not None else last_close
    indexes = [index for index, bar in enumerate(prepared.bars) if start <= bar.origin_time < stop]
    if not indexes:
        msg = "profile range contains no bars"
        raise InsufficientDataError(msg)
    if prepared.bars[indexes[0]].origin_time > start and start < prepared.bars[0].origin_time:
        msg = "profile range starts before the available bars"
        raise InsufficientDataError(msg)
    complete = end is not None and last_close >= end
    if require_end and not complete:
        # Still return a pending window so the caller can show it without logging an event.
        complete = False
    return _window_from_indexes(
        prepared,
        indexes,
        start,
        stop,
        None,
        "full" if complete else "prefix",
    )


def _window_from_indexes(
    prepared: PreparedSeries,
    indexes: list[int],
    start: datetime,
    end: datetime,
    session_day: date | None,
    coverage: str,
    confirm_at: datetime | None = None,
) -> ProfileWindow:
    codes = {prepared.bars[index].contract_code for index in indexes}
    if len(codes) > 1:
        msg = "refusing to merge a volume profile across contracts"
        raise InsufficientDataError(msg)
    complete = coverage == "full"
    confirmation = None
    if complete and indexes:
        confirmation = confirm_at
        if confirmation is None:
            confirmation = bar_close_time(prepared.bars[indexes[-1]])
    return ProfileWindow(
        start=start,
        end=end,
        origin_time=start,
        confirmation_time=confirmation if complete else None,
        complete=complete,
        contract_code=next(iter(codes)) if codes else None,
        session_day=session_day,
        bar_indexes=tuple(indexes),
    )


def _eth_window(
    prepared: PreparedSeries,
    calendar: SessionCalendar,
    session_day: date,
    indexes: list[int],
    *,
    is_first: bool,
    is_last: bool,
) -> ProfileWindow | None:
    if not session_has_overnight(calendar):
        msg = "ETH profile requires an RTH sub-session on the calendar"
        raise InsufficientDataError(msg)
    trading = trading_bounds(calendar, session_day)
    rth = rth_bounds(calendar, session_day)
    if len(trading) != 1 or rth is None:
        msg = "ETH profile requires an RTH sub-session on the calendar"
        raise InsufficientDataError(msg)
    opens, closes = trading[0]
    pre = _inside(prepared, indexes, opens, rth[0])
    post = _inside(prepared, indexes, rth[1], closes)
    pre_coverage = _classify(prepared, pre, opens, rth[0], is_first=is_first, is_last=is_last)
    post_coverage = _classify(prepared, post, rth[1], closes, is_first=is_first, is_last=is_last)
    kind = _combine_eth(pre_coverage, post_coverage, is_last=is_last)
    if kind in {"empty", "censored"}:
        return None
    return _window_from_indexes(prepared, pre + post, opens, closes, session_day, kind)


def _combine_eth(pre: CoverageKind, post: CoverageKind, *, is_last: bool) -> CoverageKind:
    if pre == "full" and post == "full":
        return "full"
    developing = {"full", "prefix", "empty"}
    if is_last and pre in developing and post in developing and (pre != "empty" or post != "empty"):
        return "prefix"
    if pre in {"empty", "censored"} and post in {"empty", "censored"}:
        return "empty" if pre == "empty" and post == "empty" else "censored"
    msg = "missing bar inside an ETH window"
    raise InsufficientDataError(msg)


def _groups(prepared: PreparedSeries, calendar: SessionCalendar) -> list[tuple[date, list[int]]]:
    groups: list[tuple[date, list[int]]] = []
    current: date | None = None
    bucket: list[int] = []
    for index, bar in enumerate(prepared.bars):
        located = locate_session(calendar, bar.origin_time)
        if located is None:
            msg = f"bar {bar.origin_time.isoformat()} falls outside the session calendar"
            raise InsufficientDataError(msg)
        session_day = located[0]
        if current is None:
            current = session_day
        if session_day != current:
            groups.append((current, bucket))
            current = session_day
            bucket = []
        bucket.append(index)
    if current is not None:
        groups.append((current, bucket))
    return groups


def _inside(
    prepared: PreparedSeries, indexes: list[int], start: datetime, end: datetime
) -> list[int]:
    return [index for index in indexes if start <= prepared.bars[index].origin_time < end]


def _classify(
    prepared: PreparedSeries,
    indexes: list[int],
    start: datetime,
    end: datetime,
    *,
    is_first: bool,
    is_last: bool,
) -> CoverageKind:
    step = bar_step(prepared.bars[0].timeframe)
    expected = expected_origins(start, end, step)
    present = [prepared.bars[index].origin_time for index in indexes]
    if not expected:
        return "empty"
    if not present:
        reached_end = any(bar.origin_time >= end for bar in prepared.bars)
        if not reached_end:
            return "empty"
        if is_first:
            return "censored"
        msg = "missing bar inside a profile window"
        raise InsufficientDataError(msg)
    expected_set = set(expected)
    if any(origin not in expected_set for origin in present):
        # ETH and composites pass a non-contiguous index list against a wide window.
        # Fall back to "the bars we were given are a contiguous subset of some expected grid"
        # only when every present origin is on the trading grid of its own span. Callers that
        # need a strict session use a tight [start, end).
        if _contiguous_on_grid(present, expected):
            return _classify_block(present, expected, is_first=is_first, is_last=is_last)
        msg = "bar inside a profile window is not on the timeframe grid"
        raise InsufficientDataError(msg)
    return _classify_block(present, expected, is_first=is_first, is_last=is_last)


def _contiguous_on_grid(present: list[datetime], expected: list[datetime]) -> bool:
    return all(origin in set(expected) for origin in present)


def _classify_block(
    present: list[datetime],
    expected: list[datetime],
    *,
    is_first: bool,
    is_last: bool,
) -> CoverageKind:
    start = expected.index(present[0])
    end = expected.index(present[-1])
    block = expected[start : end + 1]
    if block != present:
        msg = "missing bar inside a profile window"
        raise InsufficientDataError(msg)
    if start == 0 and end == len(expected) - 1:
        return "full"
    if start == 0 and is_last:
        return "prefix"
    if start > 0 and end == len(expected) - 1 and is_first:
        return "censored"
    msg = "missing bar inside a profile window"
    raise InsufficientDataError(msg)
