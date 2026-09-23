"""Detector protocol and registry. No detector logic lives here."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field, JsonValue

from trading_core.domain.common import CalcVersion, DomainModel, SessionScope
from trading_core.domain.instruments import FuturesContract, Instrument, SessionCalendar
from trading_core.domain.market import BarSeries, TradeBatch
from trading_core.domain.ta import DetectorName, TAEvent, TAFeature


class InsufficientDataError(ValueError):
    """Raised when warm-up is inadequate or required data (e.g. trades for VP) is missing."""


class DetectorInput(DomainModel):
    instrument: Instrument
    contract: FuturesContract | None = None
    calendar: SessionCalendar
    session: SessionScope
    bars: BarSeries
    trades: TradeBatch | None = Field(
        default=None, description="Required by volume profile; bars alone never fake volume."
    )
    snapshot_id: UUID
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    prior_features: list[TAFeature] = Field(
        default_factory=list,
        description="Previously confirmed features (pivots, levels) the detector may consume.",
    )


class DetectorOutput(DomainModel):
    features: list[TAFeature]
    events: list[TAEvent]
    warnings: list[str] = Field(default_factory=list)


@runtime_checkable
class Detector(Protocol):
    @property
    def name(self) -> DetectorName: ...

    @property
    def calc_version(self) -> CalcVersion: ...

    def default_parameters(self) -> dict[str, JsonValue]: ...

    def run(self, data: DetectorInput) -> DetectorOutput: ...


class DetectorRegistry:
    def __init__(self) -> None:
        self._detectors: dict[str, Detector] = {}

    def register(self, detector: Detector) -> None:
        key = f"{detector.name}@{detector.calc_version}"
        if key in self._detectors:
            msg = f"detector already registered: {key}"
            raise ValueError(msg)
        self._detectors[key] = detector

    def get(self, name: DetectorName, calc_version: str) -> Detector:
        return self._detectors[f"{name}@{calc_version}"]

    def names(self) -> list[str]:
        return sorted(self._detectors)
