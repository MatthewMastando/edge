"""Artifacts, immutable revisions and the single autosaved draft."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import Field, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from trading_api.auth import UserDep
from trading_api.dependencies import DatabaseDep
from trading_core.domain.common import DecimalStr, DomainModel, Stance
from trading_core.domain.thesis import RiskCalculation, Thesis
from trading_core.storage.repositories import artifacts
from trading_core.storage.repositories.common import (
    as_datetime,
    as_int,
    as_json_dict,
    as_str,
    as_str_or_none,
    as_uuid,
    as_uuid_or_none,
)

router = APIRouter(prefix="/v1", tags=["artifacts"])


class ArtifactSummary(DomainModel):
    id: UUID
    title: str
    kind: str
    tags: list[str] = Field(default_factory=list)
    instrument_id: UUID | None = None
    contract_code: str | None = None
    current_revision_id: UUID | None = None
    updated_at: datetime


class ArtifactDetail(ArtifactSummary):
    conversation_id: UUID | None = None
    created_at: datetime


class RevisionSummary(DomainModel):
    id: UUID
    revision_number: int
    change_kind: str
    created_by: str
    is_demonstration: bool
    provenance: str
    created_at: datetime
    presentation_markdown: str


class RevisionDetail(RevisionSummary):
    artifact_id: UUID
    parent_revision_id: UUID | None = None
    run_id: UUID | None = None
    structured: dict[str, JsonValue]


class UserRevisionBody(DomainModel):
    """User save. Numerical fields overlay the parent thesis; feature levels are left untouched."""

    base_revision_id: UUID
    presentation_markdown: str = Field(min_length=1, max_length=100_000)
    stance: Stance
    entry: DecimalStr | None = None
    invalidation: DecimalStr | None = None
    target: DecimalStr | None = None
    contracts: int | None = Field(default=None, ge=0)
    estimated_costs: DecimalStr | None = None
    unset_reason: str | None = Field(default=None, max_length=2000)


class DraftBody(DomainModel):
    base_revision_id: UUID | None = None
    structured: dict[str, JsonValue] | None = None
    presentation_markdown: str | None = Field(default=None, max_length=100_000)


class DraftResponse(DomainModel):
    artifact_id: UUID
    base_revision_id: UUID | None = None
    structured: dict[str, JsonValue] | None = None
    presentation_markdown: str | None = None
    updated_at: datetime | None = None


def _tags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _summary(row: dict[str, object]) -> ArtifactSummary:
    return ArtifactSummary(
        id=as_uuid(row["id"]),
        title=as_str(row["title"]),
        kind=as_str(row["kind"]),
        tags=_tags(row.get("tags")),
        instrument_id=as_uuid_or_none(row.get("instrument_id")),
        contract_code=as_str_or_none(row.get("contract_code")),
        current_revision_id=as_uuid_or_none(row.get("current_revision_id")),
        updated_at=as_datetime(row["updated_at"]),
    )


@router.get("/artifacts", response_model=list[ArtifactSummary], operation_id="listArtifacts")
async def list_artifacts(
    user: UserDep,
    database: DatabaseDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ArtifactSummary]:
    async with database.engine.begin() as conn:
        rows = await artifacts.list_artifacts(conn, user.id, limit=limit)
    return [_summary(row) for row in rows]


@router.get("/artifacts/{artifact_id}", response_model=ArtifactDetail, operation_id="getArtifact")
async def get_artifact(artifact_id: UUID, user: UserDep, database: DatabaseDep) -> ArtifactDetail:
    async with database.engine.begin() as conn:
        row = await _owned(conn, artifact_id, user.id)
    summary = _summary(row)
    return ArtifactDetail(
        **summary.model_dump(),
        conversation_id=as_uuid_or_none(row.get("conversation_id")),
        created_at=as_datetime(row["created_at"]),
    )


@router.get(
    "/artifacts/{artifact_id}/revisions",
    response_model=list[RevisionSummary],
    operation_id="listArtifactRevisions",
)
async def list_revisions(
    artifact_id: UUID,
    user: UserDep,
    database: DatabaseDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[RevisionSummary]:
    async with database.engine.begin() as conn:
        await _owned(conn, artifact_id, user.id)
        rows = await artifacts.list_revisions(conn, artifact_id, limit=limit)
    return [
        RevisionSummary(
            id=as_uuid(row["id"]),
            revision_number=as_int(row["revision_number"]),
            change_kind=as_str(row["change_kind"]),
            created_by=as_str(row["created_by"]),
            is_demonstration=bool(row["is_demonstration"]),
            provenance=as_str(row["provenance"]),
            created_at=as_datetime(row["created_at"]),
            presentation_markdown=as_str(row["presentation_markdown"]),
        )
        for row in rows
    ]


@router.get(
    "/artifacts/{artifact_id}/revisions/{revision_id}",
    response_model=RevisionDetail,
    operation_id="getArtifactRevision",
)
async def get_revision(
    artifact_id: UUID, revision_id: UUID, user: UserDep, database: DatabaseDep
) -> RevisionDetail:
    async with database.engine.begin() as conn:
        await _owned(conn, artifact_id, user.id)
        row = await artifacts.get_revision(conn, revision_id)
    if row is None or as_uuid(row["artifact_id"]) != artifact_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found")
    return RevisionDetail(
        id=as_uuid(row["id"]),
        artifact_id=artifact_id,
        revision_number=as_int(row["revision_number"]),
        parent_revision_id=as_uuid_or_none(row["parent_revision_id"]),
        run_id=as_uuid_or_none(row["run_id"]),
        structured=as_json_dict(row["structured"]),
        presentation_markdown=as_str(row["presentation_markdown"]),
        change_kind=as_str(row["change_kind"]),
        created_by=as_str(row["created_by"]),
        is_demonstration=bool(row["is_demonstration"]),
        provenance=as_str(row["provenance"]),
        created_at=as_datetime(row["created_at"]),
    )


@router.get(
    "/artifacts/{artifact_id}/draft",
    response_model=DraftResponse,
    operation_id="getArtifactDraft",
)
async def get_draft(artifact_id: UUID, user: UserDep, database: DatabaseDep) -> DraftResponse:
    async with database.engine.begin() as conn:
        await _owned(conn, artifact_id, user.id)
        row = await artifacts.get_draft(conn, artifact_id)
    if row is None:
        return DraftResponse(artifact_id=artifact_id)
    structured = row["structured"]
    return DraftResponse(
        artifact_id=artifact_id,
        base_revision_id=as_uuid_or_none(row["base_revision_id"]),
        structured=None if structured is None else as_json_dict(structured),
        presentation_markdown=as_str_or_none(row["presentation_markdown"]),
        updated_at=as_datetime(row["updated_at"]),
    )


@router.put(
    "/artifacts/{artifact_id}/draft",
    response_model=DraftResponse,
    operation_id="saveArtifactDraft",
)
async def save_draft(
    artifact_id: UUID, body: DraftBody, user: UserDep, database: DatabaseDep
) -> DraftResponse:
    """Autosave the editable presentation. This does not create a revision.

    An older clientUpdatedAt does not overwrite a newer draft.
    """
    async with database.engine.begin() as conn:
        await _owned(conn, artifact_id, user.id)
        existing = await artifacts.get_draft(conn, artifact_id)
        if draft_write_is_stale(existing, body.structured):
            row = existing
        else:
            await artifacts.upsert_draft(
                conn,
                artifact_id=artifact_id,
                base_revision_id=body.base_revision_id,
                structured=body.structured,
                presentation_markdown=body.presentation_markdown,
            )
            row = await artifacts.get_draft(conn, artifact_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    structured = row["structured"]
    return DraftResponse(
        artifact_id=artifact_id,
        base_revision_id=as_uuid_or_none(row["base_revision_id"]),
        structured=None if structured is None else as_json_dict(structured),
        presentation_markdown=as_str_or_none(row["presentation_markdown"]),
        updated_at=as_datetime(row["updated_at"]),
    )


@router.post(
    "/artifacts/{artifact_id}/revisions",
    response_model=RevisionDetail,
    operation_id="saveArtifactRevision",
)
async def save_revision(
    artifact_id: UUID, body: UserRevisionBody, user: UserDep, database: DatabaseDep
) -> RevisionDetail:
    """Persist an immutable user revision. This does not place or change an order."""
    async with database.engine.begin() as conn:
        await _owned(conn, artifact_id, user.id)
        if not await artifacts.lock_artifact(conn, artifact_id, user.id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
        parent = await artifacts.get_revision(conn, body.base_revision_id)
        if parent is None or as_uuid(parent["artifact_id"]) != artifact_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found")
        thesis = Thesis.model_validate(as_json_dict(parent["structured"]))
        structured_changed = _structured_changed(thesis, body)
        narrative_changed = thesis.presentation_markdown != body.presentation_markdown
        if not structured_changed and not narrative_changed:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nothing to save")
        updated = _apply_user_edit(thesis, body)
        change_kind = "structured_edit" if structured_changed else "narrative_edit"
        structured = cast("dict[str, JsonValue]", updated.model_dump(mode="json"))
        revision_id, number = await artifacts.insert_revision(
            conn,
            artifact_id=artifact_id,
            parent_revision_id=body.base_revision_id,
            run_id=None,
            structured=structured,
            presentation_markdown=updated.presentation_markdown,
            change_kind=change_kind,
            created_by="user",
            is_demonstration=bool(parent["is_demonstration"]),
            provenance=as_str(parent["provenance"]),
        )
        await artifacts.set_current_revision(conn, artifact_id, revision_id)
        await artifacts.upsert_draft(
            conn,
            artifact_id=artifact_id,
            base_revision_id=revision_id,
            structured=_form_payload(body),
            presentation_markdown=updated.presentation_markdown,
        )
        row = await artifacts.get_revision(conn, revision_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found")
    return RevisionDetail(
        id=revision_id,
        artifact_id=artifact_id,
        revision_number=number,
        parent_revision_id=body.base_revision_id,
        run_id=None,
        structured=as_json_dict(row["structured"]),
        presentation_markdown=as_str(row["presentation_markdown"]),
        change_kind=change_kind,
        created_by="user",
        is_demonstration=bool(row["is_demonstration"]),
        provenance=as_str(row["provenance"]),
        created_at=as_datetime(row["created_at"]),
    )


def _structured_changed(thesis: Thesis, body: UserRevisionBody) -> bool:
    plan = thesis.plan
    risk = thesis.risk
    contracts = None if risk is None else risk.contracts
    costs = None if risk is None else risk.estimated_costs
    return (
        thesis.stance != body.stance
        or plan.entry != body.entry
        or plan.invalidation != body.invalidation
        or plan.target != body.target
        or (plan.unset_reason or None) != (body.unset_reason or None)
        or contracts != body.contracts
        or costs != body.estimated_costs
    )


def _apply_user_edit(thesis: Thesis, body: UserRevisionBody) -> Thesis:
    plan = thesis.plan.model_copy(
        update={
            "entry": body.entry,
            "invalidation": body.invalidation,
            "target": body.target,
            "unset_reason": body.unset_reason,
        }
    )
    risk = thesis.risk
    if risk is None and (body.contracts is not None or body.estimated_costs is not None):
        risk = RiskCalculation(
            account_currency="USD",
            contracts=body.contracts,
            estimated_costs=body.estimated_costs,
        )
    elif risk is not None:
        risk = risk.model_copy(
            update={"contracts": body.contracts, "estimated_costs": body.estimated_costs}
        )
    return thesis.model_copy(
        update={
            "stance": body.stance,
            "plan": plan,
            "risk": risk,
            "presentation_markdown": body.presentation_markdown,
        }
    )


def client_updated_at(structured: object) -> str | None:
    """Client clock stamp stored on an autosaved draft. Missing means the row is unversioned."""
    if structured is None:
        return None
    try:
        data = as_json_dict(structured)
    except (TypeError, ValueError):
        return None
    stamp = data.get("clientUpdatedAt")
    if isinstance(stamp, str) and stamp:
        return stamp
    return None


def draft_write_is_stale(existing: Mapping[str, object] | None, incoming: object) -> bool:
    """True when ``incoming`` is an older autosave than the draft already stored."""
    if existing is None:
        return False
    old = client_updated_at(existing.get("structured"))
    new = client_updated_at(incoming)
    if old is None or new is None:
        return False
    return new < old


def _form_payload(body: UserRevisionBody) -> dict[str, JsonValue]:
    return {
        "stance": body.stance,
        "entry": None if body.entry is None else format(body.entry, "f"),
        "invalidation": None if body.invalidation is None else format(body.invalidation, "f"),
        "target": None if body.target is None else format(body.target, "f"),
        "contracts": body.contracts,
        "estimatedCosts": None
        if body.estimated_costs is None
        else format(body.estimated_costs, "f"),
        "unsetReason": body.unset_reason or "",
    }


async def _owned(conn: AsyncConnection, artifact_id: UUID, owner_id: UUID) -> dict[str, object]:
    row = await artifacts.get_artifact(conn, artifact_id, owner_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return row
