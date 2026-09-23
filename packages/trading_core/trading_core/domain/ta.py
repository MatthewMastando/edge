"""TA feature envelope and event contract (spec section 5, last paragraph).

Every detector returns the same envelope so charts, reports, alerts and replay all read one shape.
Detector-specific payloads live in ``details`` and are versioned by ``calc_version``.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

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
    as_of: UtcDatetime
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


TAEventType = Literal[
    "confirmed",
    "touched",
    "midpoint_touched",
    "filled",
    "revisited",
    "consumed",
    "invalidated",
    "expired",
]


class TAEvent(DomainModel):
    """A state transition of a feature. Unique on
    (instrument, timeframe, detector, calc_version, origin_time, data_revision) so re-detection is
    idempotent and later bars cannot rewrite an earlier log for the same revision."""

    id: UUID
    feature_id: UUID
    instrument_id: UUID
    contract_code: str | None = None
    timeframe: Timeframe
    detector: DetectorName
    calc_version: CalcVersion
    origin_time: UtcDatetime
    data_revision: DataRevision
    event_type: TAEventType
    event_time: UtcDatetime = Field(description="Close time of the bar that produced the event.")
    direction: Direction
    levels: list[Level] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)
    provenance: Provenance
