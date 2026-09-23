"""Chart annotations copied from saved TA features.

An annotation is not a second calculation. Its prices, feature id and calc version are the
feature row that was persisted. Thesis findings point at that same annotation id.
"""

from __future__ import annotations

import json
from typing import Literal, cast
from uuid import UUID

from pydantic import JsonValue, ValidationError

from trading_core.domain.common import CalcVersion, Direction, DomainModel, UtcDatetime
from trading_core.domain.ta import DetectorName, FeatureState, Level, TAFeature
from trading_core.storage.repositories.common import as_json_dict, as_str, as_uuid

AnnotationKind = Literal["zone", "level", "marker"]

_MARKERS = frozenset({"bos", "liquidity_sweep", "rsi_divergence"})
_DETECTORS = frozenset(
    {
        "volume_profile",
        "fvg",
        "liquidity_sweep",
        "bos",
        "order_block",
        "rsi_divergence",
        "swing_pivot",
        "liquidity_pool",
        "atr",
        "rsi",
        "vwap",
        "session_levels",
        "correlation",
    }
)


class ChartAnnotation(DomainModel):
    """Geometry for one saved feature. ``levels`` are the feature's levels, not a new estimate."""

    id: str
    feature_id: UUID
    detector: DetectorName
    calc_version: CalcVersion
    kind: AnnotationKind
    levels: list[Level]
    direction: Direction
    state: FeatureState
    origin_time: UtcDatetime
    confirmation_time: UtcDatetime | None = None


class SavedCalculation(DomainModel):
    """A feature row plus the annotation stored on that row."""

    feature_id: UUID
    detector: DetectorName
    calc_version: CalcVersion
    levels: list[Level]
    annotation: ChartAnnotation


def annotation_id_for(feature_id: UUID) -> str:
    return f"ann:{feature_id}"


def annotation_kind(feature: TAFeature) -> AnnotationKind:
    roles = {level.role for level in feature.levels}
    if "zone_lower" in roles and "zone_upper" in roles:
        return "zone"
    if feature.detector in _MARKERS:
        return "marker"
    return "level"


def annotation_from_feature(feature: TAFeature) -> ChartAnnotation:
    return ChartAnnotation(
        id=annotation_id_for(feature.id),
        feature_id=feature.id,
        detector=feature.detector,
        calc_version=feature.calc_version,
        kind=annotation_kind(feature),
        levels=list(feature.levels),
        direction=feature.direction,
        state=feature.state,
        origin_time=feature.origin_time,
        confirmation_time=feature.confirmation_time,
    )


def stamp_feature(feature: TAFeature) -> TAFeature:
    """Attach the chart annotation to the feature payload before it is saved."""
    annotation = annotation_from_feature(feature)
    details = dict(feature.details)
    details["chart_annotation"] = cast("JsonValue", annotation.model_dump(mode="json"))
    return feature.model_copy(update={"details": details})


def same_levels(left: list[Level], right: list[Level]) -> bool:
    return _identity(left) == _identity(right)


def calculations_from_rows(rows: list[dict[str, object]]) -> dict[UUID, SavedCalculation]:
    """Parse saved feature rows. A row that does not carry a matching annotation is omitted."""
    found: dict[UUID, SavedCalculation] = {}
    for row in rows:
        calculation = _calculation(row)
        if calculation is not None:
            found[calculation.feature_id] = calculation
    return found


def _identity(levels: list[Level]) -> list[tuple[str, object, str]]:
    return sorted((level.name, level.price, level.role) for level in levels)


def _calculation(row: dict[str, object]) -> SavedCalculation | None:
    feature_id = as_uuid(row["id"])
    detector = _detector(row.get("detector"))
    levels = _levels(row.get("levels"))
    annotation = _stored_annotation(as_json_dict(row.get("details")))
    if detector is None or levels is None or annotation is None:
        return None
    try:
        version = as_str(row["calc_version"])
        saved = SavedCalculation(
            feature_id=feature_id,
            detector=detector,
            calc_version=version,
            levels=levels,
            annotation=annotation,
        )
    except (ValidationError, TypeError):
        return None
    if not _aligned(saved, feature_id, detector):
        return None
    return saved


def _stored_annotation(details: dict[str, JsonValue]) -> ChartAnnotation | None:
    raw = details.get("chart_annotation")
    if not isinstance(raw, dict):
        return None
    try:
        return ChartAnnotation.model_validate(raw)
    except ValidationError:
        return None


def _aligned(saved: SavedCalculation, feature_id: UUID, detector: DetectorName) -> bool:
    annotation = saved.annotation
    return (
        annotation.feature_id == feature_id
        and annotation.id == annotation_id_for(feature_id)
        and annotation.detector == detector
        and annotation.calc_version == saved.calc_version
        and same_levels(annotation.levels, saved.levels)
    )


def _detector(value: object) -> DetectorName | None:
    if isinstance(value, str) and value in _DETECTORS:
        return cast("DetectorName", value)
    return None


def _levels(value: object) -> list[Level] | None:
    parsed: object
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
    else:
        parsed = value
    if not isinstance(parsed, list):
        return None
    try:
        return [Level.model_validate(item) for item in parsed]
    except ValidationError:
        return None
