"""Deterministic TA interfaces. Detector implementations are Stage 1A (Worker A).

Contract every detector must honour (spec section 5):

- operate on completed bars only; a pivot at ``i`` becomes known at ``i+3``;
- store origin and confirmation separately;
- reject inadequate warm-up and missing data instead of guessing;
- emit :class:`~trading_core.domain.ta.TAFeature` objects stamped with ``calc_version`` and the
  ``data_revision`` of the snapshot they ran on.
"""

from trading_core.ta.interfaces import (
    Detector,
    DetectorInput,
    DetectorOutput,
    DetectorRegistry,
    InsufficientDataError,
)

__all__ = [
    "Detector",
    "DetectorInput",
    "DetectorOutput",
    "DetectorRegistry",
    "InsufficientDataError",
]
