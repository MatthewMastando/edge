"""Registered calc-version 1.0.0 detectors."""

from trading_core.ta.detectors.bos import BosDetector
from trading_core.ta.detectors.fvg import FvgDetector
from trading_core.ta.detectors.liquidity_sweep import LiquiditySweepDetector
from trading_core.ta.detectors.order_block import OrderBlockDetector
from trading_core.ta.detectors.rsi_divergence import RsiDivergenceDetector
from trading_core.ta.detectors.supporting import (
    AtrDetector,
    CorrelationDetector,
    LiquidityPoolDetector,
    RsiDetector,
    SessionLevelsDetector,
    SwingPivotDetector,
    VwapDetector,
)
from trading_core.ta.detectors.volume_profile import VolumeProfileDetector
from trading_core.ta.interfaces import Detector, DetectorRegistry

__all__ = [
    "AtrDetector",
    "BosDetector",
    "CorrelationDetector",
    "FvgDetector",
    "LiquidityPoolDetector",
    "LiquiditySweepDetector",
    "OrderBlockDetector",
    "RsiDetector",
    "RsiDivergenceDetector",
    "SessionLevelsDetector",
    "SwingPivotDetector",
    "VolumeProfileDetector",
    "VwapDetector",
    "default_registry",
]


def default_registry() -> DetectorRegistry:
    registry = DetectorRegistry()
    detectors: tuple[Detector, ...] = (
        VolumeProfileDetector(),
        FvgDetector(),
        LiquiditySweepDetector(),
        BosDetector(),
        OrderBlockDetector(),
        RsiDivergenceDetector(),
        SwingPivotDetector(),
        LiquidityPoolDetector(),
        AtrDetector(),
        RsiDetector(),
        VwapDetector(),
        SessionLevelsDetector(),
        CorrelationDetector(),
    )
    for detector in detectors:
        registry.register(detector)
    return registry
