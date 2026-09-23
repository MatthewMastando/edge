"""TA feature envelope and event contract (spec section 5, last paragraph).

Every detector returns the same envelope so charts, reports, alerts and replay all read one shape.
Detector-specific payloads live in ``details`` and are versioned by ``calc_version``.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from trading_core.domain.common import (
    CalcVersion,
    DataRevision,
    DecimalStr,
    Direction,
    DomainModel,
    Provenance,
    SessionScope,
    Timeframe,
    TimezoneName,
    UtcDatetime,
)

DetectorName = Literal[
    # the six required tools
    "volume_profile",
    "fvg",
    "liquidity_sweep",
    "bos",
    "order_block",
    "rsi_divergence",
    # supporting calculations
    "swing_pivot",
    "liquidity_pool",
    "atr",
    "rsi",
    "vwap",
    "session_levels",
    "correlation",
]

FeatureState = Literal[
    "pending",
    "confirmed",
    "touched",
    "midpoint_touched",
    "partially_filled",
    "filled",
    "revisited",
    "consumed",
    "invalidated",
    "expired",
]

LevelRole = Literal["level", "zone_upper", "zone_lower", "midpoint", "threshold", "node"]


class Level(DomainModel):
    """A named price produced by a detector (POC, VAH, zone bounds, swept level ...)."""

    name: str = Field(min_length=1, max_length=64, examples=["poc", "vah", "val", "zone_upper"])
    price: DecimalStr
    role: LevelRole = "level"


class TAFeature(DomainModel):
    """Versioned feature object. ``origin_time`` is when the pattern formed; ``confirmation_time``
    is when it became knowable (e.g. a pivot at bar i confirms at i+3). ``as_of`` is the last
    completed bar the detector saw."""

    id: UUID
    detector: DetectorName
    calc_version: CalcVersion
    instrument_id: UUID
    contract_code: str | None = None
    timeframe: Timeframe
    session: SessionScope
    session_calendar_id: str
    session_calendar_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    direction: Direction
    levels: list[Level]
    state: FeatureState
    origin_time: UtcDatetime
    origin_tz: TimezoneName
    confirmation_time: UtcDatetime | None = Field(
        default=None, description="Null while the feature is still pending."
    )
    confirmation_tz: TimezoneName | None = Field(
        default=None, description="Set exactly when ``confirmation_time`` is set."
    )
    as_of: UtcDatetime
    as_of_tz: TimezoneName
    parameters: dict[str, JsonValue] = Field(
        default_factory=dict, description="Exact detector parameters used for this calculation."
    )
    details: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Detector-specific payload (histogram bins, displacement tag, fill depth ...).",
    )
    snapshot_id: UUID
    data_revision: DataRevision
    provenance: Provenance
    warnings: list[str] = Field(
        default_factory=list,
        description="e.g. 'approximation: bar-derived volume', 'roll window excluded'.",
    )

    @model_validator(mode="after")
    def _confirmation_carries_its_zone(self) -> TAFeature:
        if (self.confirmation_time is None) != (self.confirmation_tz is None):
            msg = "confirmation_time and confirmation_tz must be set together"
            raise ValueError(msg)
        return self


TAEventType = Literal["confirmed"]
"""Detection rows only. Touch, fill and invalidation go to :class:`TAFeatureTransition`."""


class TAEvent(DomainModel):
    """The idempotent detection row for one feature.

    Unique on (instrument, contract_code, timeframe, detector, calc_version, origin_time,
    data_revision). ``contract_code`` is part of the key so two listed months of one root can
    share an origin time. ``event_type`` is always ``confirmed``; later lifecycle is a
    :class:`TAFeatureTransition`, which keeps re-detection from rewriting an earlier log.
    """

    id: UUID
    feature_id: UUID
    instrument_id: UUID
    contract_code: str | None = None
    timeframe: Timeframe
    detector: DetectorName
    calc_version: CalcVersion
    origin_time: UtcDatetime
    data_revision: DataRevision
    event_type: TAEventType = "confirmed"
    event_time: UtcDatetime = Field(description="Close time of the bar that produced the event.")
    event_tz: TimezoneName
    direction: Direction
    levels: list[Level] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)
    provenance: Provenance


class TAFeatureTransition(DomainModel):
    """Post-confirmation lifecycle (touch, fill, invalidation) for one data revision.

    Not part of the ``ta_events`` idempotency key. ``feature_id`` is the id the detector assigned
    on the :class:`TAFeature`.
    """

    feature_id: UUID
    from_state: FeatureState
    to_state: FeatureState
    bar_time: UtcDatetime = Field(description="Close time of the completed bar that caused this.")
    bar_tz: TimezoneName
    data_revision: DataRevision
    details: dict[str, JsonValue] = Field(default_factory=dict)
