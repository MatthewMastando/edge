"""Incremental replay. A longer prefix may add events; it may not rewrite ones already logged."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from trading_core.ta.envelope import event_identity, transition_identity
from trading_core.ta.interfaces import Detector, DetectorInput, InsufficientDataError
from trading_core.ta.series import bar_close_time

if TYPE_CHECKING:
    from datetime import datetime

    from trading_core.domain.market import Bar, TradeBatch
    from trading_core.domain.ta import TAEvent, TAFeatureTransition


@dataclass(frozen=True)
class ReplayStep:
    as_of: datetime
    events: tuple[TAEvent, ...]
    transitions: tuple[TAFeatureTransition, ...]


def incremental_replay(detector: Detector, data: DetectorInput) -> list[ReplayStep]:
    """Grow the completed-bar prefix. Trades are limited to those bars' time span.

    Warm-up failures on short prefixes are skipped. A later prefix that raises after an
    earlier one succeeded is a broken series, not a longer view of the same data.
    """
    ordered = sorted(data.bars.bars, key=lambda bar: bar.origin_time)
    if ordered and not ordered[-1].is_complete:
        ordered = ordered[:-1]
    completed = ordered
    steps: list[ReplayStep] = []
    succeeded = False
    for length in range(1, len(completed) + 1):
        prefix = completed[:length]
        try:
            output = detector.run(_sliced(data, prefix))
        except InsufficientDataError as exc:
            if succeeded:
                msg = f"prefix of {length} bars rejected data a shorter prefix accepted: {exc}"
                raise RuntimeError(msg) from exc
            continue
        succeeded = True
        steps.append(
            ReplayStep(
                as_of=bar_close_time(prefix[-1]),
                events=tuple(output.events),
                transitions=tuple(output.transitions),
            )
        )
    return steps


def replay_violations(steps: list[ReplayStep]) -> list[str]:
    """Empty when confirmed events and transitions are a stable, causal log."""
    problems: list[str] = []
    seen_events: dict[tuple[object, ...], str] = {}
    seen_transitions: dict[tuple[object, ...], str] = {}
    for step in steps:
        current_events: dict[tuple[object, ...], str] = {}
        for event in step.events:
            if event.event_time > step.as_of:
                stamp = event.origin_time.isoformat()
                problems.append(f"{event.detector} event at {stamp} is after as-of")
            key = event_identity(event)
            dumped = event.model_dump_json()
            if key in current_events:
                problems.append(f"duplicate event at {event.origin_time.isoformat()}")
            current_events[key] = dumped
        for key, previous in seen_events.items():
            if current_events.get(key) != previous:
                problems.append(f"confirmed event changed: {key[3]} {key[5]}")
        current_transitions: dict[tuple[object, ...], str] = {}
        for item in step.transitions:
            if item.bar_time > step.as_of:
                problems.append("transition is after as-of")
            key = transition_identity(item)
            dumped = item.model_dump_json()
            current_transitions[key] = dumped
        for key, previous in seen_transitions.items():
            if current_transitions.get(key) != previous:
                problems.append(f"transition changed: {key[1]} at {key[2]}")
        seen_events = current_events
        seen_transitions = current_transitions
    return problems


def _sliced(data: DetectorInput, bars: list[Bar]) -> DetectorInput:
    typed_bars = data.bars.model_copy(update={"bars": bars})
    trades = _slice_trades(data.trades, bars)
    return data.model_copy(update={"bars": typed_bars, "trades": trades})


def _slice_trades(batch: TradeBatch | None, bars: list[Bar]) -> TradeBatch | None:
    if batch is None or not bars:
        return batch
    start = bars[0].origin_time
    end = bar_close_time(bars[-1])
    kept = [trade for trade in batch.trades if start <= trade.trade_time < end]
    return batch.model_copy(update={"trades": kept})
