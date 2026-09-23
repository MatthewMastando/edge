"""Durable jobs and runs (spec section 3: leases, checkpoints, state machine)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

from trading_core.domain.common import DecimalStr, DomainModel, Provenance, UtcDatetime

JobState = Literal[
    "queued",
    "running",
    "partial",
    "completed",
    "failed",
    "cancelled",
    "budget_exceeded",
]

JOB_TERMINAL_STATES: frozenset[str] = frozenset(
    {"completed", "failed", "cancelled", "budget_exceeded"}
)

JOB_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset(
        {"partial", "completed", "failed", "cancelled", "budget_exceeded", "queued"}
    ),
    "partial": frozenset({"running", "completed", "failed", "cancelled", "budget_exceeded"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "budget_exceeded": frozenset(),
}
"""Allowed transitions. ``running -> queued`` is the lease-expiry requeue path."""

JobKind = Literal[
    "research",
    "ta_scan",
    "snapshot_capture",
    "scheduled_briefing",
    "hypothesis_check",
    "csv_import",
    "maintenance",
]

RunStage = Literal[
    "resolve_instrument",
    "capture_snapshot",
    "deterministic_ta",
    "gather_context",
    "synthesize",
    "critique",
    "validate",
    "repair",
    "persist",
    "notify",
]


class Job(DomainModel):
    id: UUID
    kind: JobKind
    state: JobState
    priority: int = Field(default=0, description="Higher runs first.")
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    idempotency_key: str = Field(
        min_length=1,
        max_length=256,
        description="Deduplicates routine/instrument/feature/confirmation-time combinations.",
    )
    routine_id: UUID | None = None
    conversation_id: UUID | None = None
    scheduled_for: UtcDatetime
    lease_until: UtcDatetime | None = None
    leased_by: str | None = Field(default=None, description="Worker id holding the lease.")
    checkpoint: dict[str, JsonValue] = Field(
        default_factory=dict, description="Stage outputs needed to resume after a restart."
    )
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    last_error: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None


class Usage(DomainModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    retrieval_calls: int = Field(default=0, ge=0)
    reserved_cost_usd: DecimalStr = Field(default=Decimal(0))
    actual_cost_usd: DecimalStr | None = None


class Run(DomainModel):
    """One execution of a job. A run produces at most one artifact revision."""

    id: UUID
    job_id: UUID
    conversation_id: UUID | None = None
    artifact_revision_id: UUID | None = None
    status: JobState
    current_stage: RunStage | None = None
    stages_completed: list[RunStage] = Field(default_factory=list)
    provider: str
    model: str | None = None
    prompt_version: str | None = None
    provenance: Provenance
    usage: Usage
    started_at: UtcDatetime
    finished_at: UtcDatetime | None = None
    error: str | None = None


class RunEvent(DomainModel):
    """Structured timeline entry streamed to the UI and kept for audit."""

    run_id: UUID
    sequence: int = Field(ge=0)
    at: UtcDatetime
    stage: RunStage | None = None
    level: Literal["debug", "info", "warning", "error"] = "info"
    message: str
    data: dict[str, JsonValue] = Field(default_factory=dict)
