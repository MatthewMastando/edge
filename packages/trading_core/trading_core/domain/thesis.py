"""Thesis contract (spec section 6).

The thesis is stored as structured JSON plus an editable Markdown presentation. Fields grouped
under the "structured block" (``stance``, ``plan``, ``risk``) hold the numerical assumptions:
editing them creates a recalculated version, while narrative edits preserve the original.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from trading_core.domain.common import (
    AssetClass,
    DecimalStr,
    DomainModel,
    Provenance,
    Stance,
    UtcDatetime,
)

EvidenceStance = Literal["supporting", "opposing"]


class FeatureReference(DomainModel):
    """A technical finding that resolves to a saved TA feature and its chart annotation."""

    feature_id: UUID
    annotation_id: str | None = Field(
        default=None, description="Chart annotation id rendered from the same feature."
    )
    summary: str = Field(min_length=1, max_length=1000)


class EvidenceItem(DomainModel):
    """A sourced claim. Retrieved content is evidence, never instructions."""

    stance: EvidenceStance
    claim: str = Field(min_length=1, max_length=2000)
    source_id: UUID | None = None
    excerpt_id: UUID | None = None
    url: str | None = None
    title: str | None = None
    published_at: UtcDatetime | None = None
    retrieved_at: UtcDatetime


class Catalyst(DomainModel):
    name: str
    scheduled_at: UtcDatetime | None = None
    source_id: UUID | None = None
    note: str | None = None


class CorrelatedMarket(DomainModel):
    symbol: str
    relationship: str = Field(description="Plain-language description of the linkage.")
    correlation: float | None = Field(
        default=None, ge=-1, le=1, description="Aligned-return correlation when computed."
    )
    window_bars: int | None = Field(default=None, ge=2)
    feature_id: UUID | None = None


class TradePlan(DomainModel):
    """Conditional plan. Any unsupported element stays null with ``unset_reason`` explaining why."""

    entry: DecimalStr | None = None
    invalidation: DecimalStr | None = None
    target: DecimalStr | None = None
    monitoring_criteria: list[str] = Field(default_factory=list)
    unset_reason: str | None = Field(
        default=None, description="Required when entry, invalidation or target is null."
    )


class RiskCalculation(DomainModel):
    """Hypothetical cost and risk figures. Futures amounts use verified point/tick values."""

    account_currency: str
    point_value: DecimalStr | None = None
    tick_value: DecimalStr | None = None
    contracts: int | None = Field(default=None, ge=0)
    risk_per_contract: DecimalStr | None = None
    total_risk: DecimalStr | None = None
    estimated_costs: DecimalStr | None = None
    reward_to_risk: DecimalStr | None = None
    assumptions: list[str] = Field(default_factory=list)
    is_hypothetical: Literal[True] = True


class ThesisVersions(DomainModel):
    model: str | None = Field(default=None, description="Model name as configured server-side.")
    provider: str
    prompt_version: str
    harness_version: str
    tool_versions: dict[str, str] = Field(default_factory=dict)


class ValidationCheck(DomainModel):
    name: str = Field(examples=["schema", "numeric_crosscheck", "evidence_ids_exist"])
    passed: bool
    detail: str | None = None


class ValidationResult(DomainModel):
    passed: bool
    checks: list[ValidationCheck]
    repair_attempted: bool = False


class Thesis(DomainModel):
    id: UUID
    run_id: UUID | None = None
    instrument_id: UUID
    symbol: str
    asset_class: AssetClass
    contract_code: str | None = Field(
        default=None, description="Actual futures contract when applicable."
    )
    venue: str
    horizon: str = Field(examples=["intraday", "2-5 sessions", "swing"])
    as_of: UtcDatetime
    expires_at: UtcDatetime | None = None
    # --- structured block: edits here trigger recalculation in a new version ---
    stance: Stance
    plan: TradePlan
    risk: RiskCalculation | None = None
    # --- findings and narrative ---
    technical_findings: list[FeatureReference]
    market_narrative: str
    macro_context: str
    catalysts: list[Catalyst] = Field(default_factory=list)
    correlated_markets: list[CorrelatedMarket] = Field(default_factory=list)
    supporting_evidence: list[EvidenceItem] = Field(default_factory=list)
    opposing_evidence: list[EvidenceItem] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    uncertainty: str
    rationale: str = Field(max_length=4000)
    versions: ThesisVersions
    validation: ValidationResult
    presentation_markdown: str = Field(description="Editable presentation of this thesis.")
    provenance: Provenance
    is_demonstration: bool = Field(
        description="True whenever provenance is not live; UI must label it prominently."
    )
