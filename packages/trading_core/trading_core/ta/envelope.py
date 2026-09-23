"""Build the shared feature / event / transition envelope.

Event identity matches the Stage 0 unique key: instrument, contract code, timeframe, detector,
calc version, origin time, data revision. Detectors must give each emitted row its own origin
time. Lifecycle after confirmation is a transition, not a second event.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from trading_core.domain.ta import (
    DetectorName,
    FeatureState,
    Level,
    LevelRole,
    TAEvent,
    TAFeature,
    TAFeatureTransition,
)
from trading_core.ta.interfaces import DetectorInput, DetectorOutput
from trading_core.ta.series import PreparedSeries, bar_close_time

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from pydantic import JsonValue

    from trading_core.domain.common import Direction, SessionScope

TA_NAMESPACE = uuid.UUID("b7e2c4a1-5d18-4f6e-8c3a-9e0d1f2a4b60")


def decimal_str(value: Decimal) -> str:
    return format(value, "f")


def time_str(value: datetime) -> str:
    return value.isoformat()


def level(name: str, price: Decimal, role: LevelRole = "level") -> Level:
    return Level(name=name, price=price, role=role)


@dataclass
class TransitionDraft:
    from_state: FeatureState
    to_state: FeatureState
    bar_time: datetime
    bar_tz: str
    details: dict[str, JsonValue]


@dataclass
class FeatureDraft:
    direction: Direction
    session: SessionScope
    levels: list[Level]
    state: FeatureState
    origin_time: datetime
    origin_tz: str
    confirmation_time: datetime | None
    confirmation_tz: str | None
    contract_code: str | None
    details: dict[str, JsonValue]
    warnings: list[str] = field(default_factory=list)
    event_levels: list[Level] | None = None
    event_details: dict[str, JsonValue] | None = None
    event_time: datetime | None = None
    event_direction: Direction | None = None
    transitions: list[TransitionDraft] = field(default_factory=list)


def feature_uuid(
    *,
    instrument_id: uuid.UUID,
    contract_code: str | None,
    timeframe: str,
    detector: str,
    calc_version: str,
    origin_time: datetime,
    data_revision: str,
) -> uuid.UUID:
    payload = "|".join(
        (
            str(instrument_id),
            contract_code or "",
            timeframe,
            detector,
            calc_version,
            origin_time.isoformat(),
            data_revision,
        )
    )
    return uuid.uuid5(TA_NAMESPACE, payload)


def build_output(
    *,
    detector: DetectorName,
    calc_version: str,
    data: DetectorInput,
    prepared: PreparedSeries,
    parameters: dict[str, JsonValue],
    drafts: list[FeatureDraft],
    warnings: list[str],
) -> DetectorOutput:
    as_of_bar = prepared.bars[-1]
    as_of = bar_close_time(as_of_bar)
    features: list[TAFeature] = []
    events: list[TAEvent] = []
    transitions: list[TAFeatureTransition] = []
    seen: set[tuple[object, ...]] = set()
    for draft in drafts:
        feature, event, drafted = _materialize(
            detector=detector,
            calc_version=calc_version,
            data=data,
            parameters=parameters,
            draft=draft,
            as_of=as_of,
            as_of_tz=as_of_bar.origin_tz,
        )
        key = _event_identity(feature)
        if key in seen:
            msg = (
                f"{detector} emitted two rows with origin {draft.origin_time.isoformat()} "
                "and the same contract; the Stage 0 event key has no level discriminator"
            )
            raise RuntimeError(msg)
        seen.add(key)
        features.append(feature)
        if event is not None:
            events.append(event)
        transitions.extend(drafted)
    features.sort(key=_feature_sort)
    events.sort(key=_event_sort)
    transitions.sort(key=lambda item: (item.bar_time, item.to_state, str(item.feature_id)))
    run_warnings = list(warnings)
    if prepared.dropped_incomplete:
        run_warnings.append("trailing incomplete bar ignored")
    return DetectorOutput(
        features=features, events=events, transitions=transitions, warnings=run_warnings
    )


def _materialize(
    *,
    detector: DetectorName,
    calc_version: str,
    data: DetectorInput,
    parameters: dict[str, JsonValue],
    draft: FeatureDraft,
    as_of: datetime,
    as_of_tz: str,
) -> tuple[TAFeature, TAEvent | None, list[TAFeatureTransition]]:
    if (draft.confirmation_time is None) != (draft.confirmation_tz is None):
        msg = "confirmation time and timezone must be set together"
        raise RuntimeError(msg)
    if draft.confirmation_time is not None and draft.confirmation_time < draft.origin_time:
        msg = "confirmation time is before origin time"
        raise RuntimeError(msg)
    feature_id = feature_uuid(
        instrument_id=data.instrument.id,
        contract_code=draft.contract_code,
        timeframe=data.bars.timeframe,
        detector=detector,
        calc_version=calc_version,
        origin_time=draft.origin_time,
        data_revision=data.bars.data_revision,
    )
    feature = TAFeature(
        id=feature_id,
        detector=detector,
        calc_version=calc_version,
        instrument_id=data.instrument.id,
        contract_code=draft.contract_code,
        timeframe=data.bars.timeframe,
        session=draft.session,
        session_calendar_id=data.calendar.id,
        session_calendar_version=data.calendar.version,
        direction=draft.direction,
        levels=list(draft.levels),
        state=draft.state,
        origin_time=draft.origin_time,
        origin_tz=draft.origin_tz,
        confirmation_time=draft.confirmation_time,
        confirmation_tz=draft.confirmation_tz,
        as_of=as_of,
        as_of_tz=as_of_tz,
        parameters=parameters,
        details=draft.details,
        snapshot_id=data.snapshot_id,
        data_revision=data.bars.data_revision,
        provenance=data.bars.provenance,
        warnings=list(draft.warnings),
    )
    event: TAEvent | None = None
    if draft.confirmation_time is not None and draft.state != "pending":
        event_time = draft.event_time if draft.event_time is not None else draft.confirmation_time
        event = TAEvent(
            id=uuid.uuid5(TA_NAMESPACE, f"{feature_id}|event"),
            feature_id=feature_id,
            instrument_id=data.instrument.id,
            contract_code=draft.contract_code,
            timeframe=data.bars.timeframe,
            detector=detector,
            calc_version=calc_version,
            origin_time=draft.origin_time,
            data_revision=data.bars.data_revision,
            event_type="confirmed",
            event_time=event_time,
            event_tz=draft.confirmation_tz or draft.origin_tz,
            direction=draft.event_direction or draft.direction,
            levels=list(draft.event_levels if draft.event_levels is not None else draft.levels),
            details=dict(draft.event_details if draft.event_details is not None else draft.details),
            provenance=data.bars.provenance,
        )
    transitions = [
        TAFeatureTransition(
            feature_id=feature_id,
            from_state=item.from_state,
            to_state=item.to_state,
            bar_time=item.bar_time,
            bar_tz=item.bar_tz,
            data_revision=data.bars.data_revision,
            details=item.details,
        )
        for item in draft.transitions
    ]
    return feature, event, transitions


def _event_identity(feature: TAFeature) -> tuple[object, ...]:
    return (
        feature.instrument_id,
        feature.contract_code,
        feature.timeframe,
        feature.detector,
        feature.calc_version,
        feature.origin_time,
        feature.data_revision,
    )


def _feature_sort(feature: TAFeature) -> tuple[datetime, str, str]:
    return (feature.origin_time, feature.direction, feature.state)


def _event_sort(event: TAEvent) -> tuple[datetime, datetime, str]:
    return (event.origin_time, event.event_time, event.direction)


def quantize(value: Decimal, places: Decimal) -> Decimal:
    return value.quantize(places)


EventIdentity = tuple[object, ...]


def event_identity(event: TAEvent) -> EventIdentity:
    return (
        event.instrument_id,
        event.contract_code,
        event.timeframe,
        event.detector,
        event.calc_version,
        event.origin_time,
        event.data_revision,
    )


TransitionIdentity = tuple[object, ...]


def transition_identity(item: TAFeatureTransition) -> TransitionIdentity:
    return (item.feature_id, item.to_state, item.bar_time, item.data_revision)
