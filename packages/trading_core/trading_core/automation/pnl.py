"""Simulated P&L. The result is hypothetical and is never written to imported fills."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

PnlLabel = Literal["simulated"]
SIMULATED: PnlLabel = "simulated"


def simulated_pnl(
    *,
    stance: str,
    entry: Decimal,
    exit_price: Decimal,
    multiplier: Decimal,
    cost: Decimal,
) -> Decimal:
    """Point-value P&L for one explicit fill and exit, minus the stated cost."""
    sign = Decimal(1) if stance == "bullish" else Decimal(-1)
    if stance not in {"bullish", "bearish"}:
        return Decimal(0)
    return (exit_price - entry) * sign * multiplier - cost
