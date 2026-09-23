"""Initial research limits from spec section 6."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from trading_core.domain.common import DecimalStr, DomainModel


class ResearchLimits(DomainModel):
    max_external_retrievals: int = Field(default=12, ge=0)
    max_evidence_tokens: int = Field(default=25_000, ge=1)
    max_model_iterations: int = Field(default=6, ge=1)
    max_repair_attempts: int = Field(default=1, ge=0, le=1)
    timeout_seconds: float = Field(default=180, ge=0)
    monthly_ai_search_usd: DecimalStr = Field(default=Decimal("100"))
    monthly_market_data_usd: DecimalStr = Field(
        default=Decimal("0"),
        description="Separate from the AI/search ceiling. Zero records cost and does not block.",
    )
    llm_reserve_usd: DecimalStr = Field(default=Decimal("0.02"))
    retrieval_reserve_usd: DecimalStr = Field(default=Decimal("0.01"))


def estimate_tokens(text: str) -> int:
    """Rough evidence-pack budget. Four characters per token is enough to enforce the cap."""
    return max(1, (len(text) + 3) // 4) if text else 0
