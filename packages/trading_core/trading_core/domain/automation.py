"""Automation contracts: routines, alerts, budgets and research outcomes."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

from trading_core.domain.common import DecimalStr, DomainModel, Stance, Timeframe, UtcDatetime

RoutineKind = Literal["scheduled_briefing", "ta_trigger", "manual"]
ResearchTier = Literal["full", "brief"]
CryptoMonitoring = Literal["always", "calendar"]
AlertKind = Literal[
    "new_research", "material_change", "run_failed", "budget", "source_failure", "import"
]
HypothesisStatus = Literal[
    "open", "triggered", "invalidated", "target_hit", "expired", "untriggered"
]
EntryState = Literal["triggered", "untriggered"]
ObservationEvent = Literal[
    "checkpoint", "entry_triggered", "invalidation_hit", "target_hit", "expired"
]


class Routine(DomainModel):
    id: UUID
    owner_id: UUID | None = None
    name: str
    kind: RoutineKind
    enabled: bool = True
    schedule_cron: str | None = None
    schedule_timezone: str = "America/New_York"
    instrument_ids: list[UUID] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    symbol_by_instrument: dict[str, str] = Field(default_factory=dict)
    tier: ResearchTier = "brief"
    event_allowlist: list[str] = Field(default_factory=list)
    cooldown_seconds: int = Field(default=14_400, ge=0)
    daily_cap: int = Field(default=6, ge=0)
    crypto_monitoring: CryptoMonitoring = "always"
    question: str | None = None
    timeframe: Timeframe = "5m"
    last_run_at: UtcDatetime | None = None
    next_run_at: UtcDatetime | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class RoutineCreate(DomainModel):
    name: str = Field(min_length=1, max_length=120)
    kind: RoutineKind
    schedule_cron: str | None = None
    schedule_timezone: str = "America/New_York"
    symbols: list[str] = Field(min_length=1, max_length=20)
    tier: ResearchTier = "brief"
    event_allowlist: list[str] = Field(default_factory=list)
    cooldown_seconds: int = Field(default=14_400, ge=0)
    daily_cap: int = Field(default=6, ge=0)
    crypto_monitoring: CryptoMonitoring = "always"
    question: str | None = Field(default=None, max_length=2000)
    timeframe: Timeframe = "5m"


class Notification(DomainModel):
    id: UUID
    kind: AlertKind
    severity: Literal["info", "warning", "error"]
    title: str
    body: str | None = None
    run_id: UUID | None = None
    artifact_id: UUID | None = None
    read_at: UtcDatetime | None = None
    created_at: UtcDatetime


class BudgetStatus(DomainModel):
    """One monthly ceiling. Market-data spend is never included in the AI/search row."""

    category: Literal["ai_search", "market_data"]
    period_start: date
    limit_usd: DecimalStr
    spent_usd: DecimalStr
    enforced: bool = Field(description="False when a zero market-data ceiling means record-only.")


class BudgetUpdate(DomainModel):
    limit_usd: DecimalStr = Field(ge=0)


class HypothesisObservationView(DomainModel):
    id: UUID
    observed_at: UtcDatetime
    observed_tz: str
    price: DecimalStr
    event: ObservationEvent
    data_revision: str
    note: str | None = None


class HypothesisOutcome(DomainModel):
    """Frozen thesis plus what price did afterward.

    ``simulated_pnl`` uses explicit fill, exit and cost assumptions. It is labeled
    ``simulated`` and is not a row in imported fills.
    """

    id: UUID
    artifact_revision_id: UUID
    instrument_id: UUID
    symbol: str
    contract_code: str | None = None
    stance: Stance
    entry: DecimalStr | None = None
    invalidation: DecimalStr | None = None
    target: DecimalStr | None = None
    horizon: str
    frozen_at: UtcDatetime
    status: HypothesisStatus
    entry_state: EntryState
    subsequent_move: DecimalStr | None = None
    simulated_pnl: DecimalStr | None = None
    simulated_pnl_currency: str | None = None
    pnl_label: Literal["simulated"] = "simulated"
    real_fills_included: Literal[False] = False
    assumptions: dict[str, JsonValue] = Field(default_factory=dict)
    observations: list[HypothesisObservationView] = Field(default_factory=list)
