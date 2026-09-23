"""Deterministic technical analysis, calc version 1.0.0.

Charts, reports, alerts and replay share :class:`~trading_core.domain.ta.TAFeature` objects
produced by the detectors in :mod:`trading_core.ta.detectors`.
"""

from trading_core.ta.constants import CALC_VERSION
from trading_core.ta.detectors import default_registry
from trading_core.ta.interfaces import (
    Detector,
    DetectorInput,
    DetectorOutput,
    DetectorRegistry,
    InsufficientDataError,
)
from trading_core.ta.replay import ReplayStep, incremental_replay, replay_violations

__all__ = [
    "CALC_VERSION",
    "Detector",
    "DetectorInput",
    "DetectorOutput",
    "DetectorRegistry",
    "InsufficientDataError",
    "ReplayStep",
    "default_registry",
    "incremental_replay",
    "replay_violations",
]
