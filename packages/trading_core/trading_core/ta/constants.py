"""Frozen calculation defaults for calc version 1.0.0.

Bump :data:`CALC_VERSION` when any rule in this module changes. Charts, reports, alerts
and replay all read the version off the feature, so silent edits are not allowed.
"""

from __future__ import annotations

from decimal import Decimal

CALC_VERSION = "1.0.0"

PIVOT_WING = 3
ATR_PERIOD = 14
RSI_PERIOD = 14
DISPLACEMENT_BODY_RATIO = Decimal("0.60")
VALUE_AREA_FRACTION = Decimal("0.70")
POOL_MIN_TOUCHES = 2
POOL_MIN_SEPARATION = 3
POOL_MAX_SPAN_TICKS = 2
SWEEP_TICKS = 1
BOS_TICKS = 1
FVG_MIN_TICKS = 1
OB_LOOKBACK = 5
RSI_DIV_MIN_SEPARATION = 5
RSI_DIV_MAX_SEPARATION = 60
RSI_DIV_MIN_POINTS = Decimal("2")
NODE_MA_BINS = 3
NODE_EXTREMUM_WING = 2
NODE_HVN_PERCENTILE = Decimal("0.75")
NODE_LVN_PERCENTILE = Decimal("0.25")
MIN_ALIGNED_RETURNS = 3
COMPOSITE_SESSIONS = 5

# Bar-only volume profile. Never presented as trade volume-at-price.
BAR_APPROXIMATION_WARNING = "approximation: bar-range volume is not trade volume-at-price"

# Published indicator and correlation values are rounded half-even so fixture
# comparisons do not depend on binary float. Wilder state itself stays exact;
# only the value written onto a feature is quantized.
PUBLISHED_PLACES = Decimal("0.00000001")
