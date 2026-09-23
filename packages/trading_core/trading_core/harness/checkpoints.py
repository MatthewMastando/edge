"""Per-stage checkpoint stored on ``jobs.checkpoint``."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from pydantic import Field, JsonValue

from trading_core.domain.common import DomainModel
from trading_core.domain.jobs import RunStage


class ResearchCheckpoint(DomainModel):
    run_id: UUID | None = None
    stages_completed: list[RunStage] = Field(default_factory=list)
    symbol: str | None = None
    instrument_id: UUID | None = None
    contract_code: str | None = None
    venue: str | None = None
    asset_class: str | None = None
    calendar_id: str | None = None
    calendar_version: str | None = None
    tick_value: str | None = None
    point_value: str | None = None
    data_revision: str | None = None
    as_of: str | None = None
    snapshot_ids: list[UUID] = Field(default_factory=list)
    bars_snapshot_id: UUID | None = None
    feature_ids: list[UUID] = Field(default_factory=list)
    feature_summaries: list[dict[str, JsonValue]] = Field(default_factory=list)
    source_ids: list[UUID] = Field(default_factory=list)
    excerpt_ids: list[UUID] = Field(default_factory=list)
    stub_detectors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    thesis: dict[str, JsonValue] | None = None
    validation_passed: bool | None = None
    repair_attempted: bool = False
    artifact_id: UUID | None = None
    revision_id: UUID | None = None
    notified: bool = False
    partial_research: bool = False
    stop_reason: str | None = None
    event_sequence: int = 0
    tool_sequence: int = 0
    retrievals_used: int = 0


def dump_checkpoint(checkpoint: ResearchCheckpoint) -> dict[str, JsonValue]:
    return cast("dict[str, JsonValue]", checkpoint.model_dump(mode="json"))
