"""Artifacts, immutable revisions and the single autosaved draft."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import Field, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from trading_api.auth import UserDep
from trading_api.dependencies import DatabaseDep
from trading_core.domain.common import DomainModel
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
    """Autosave the editable presentation. This does not create a revision."""
    async with database.engine.begin() as conn:
        await _owned(conn, artifact_id, user.id)
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


async def _owned(conn: AsyncConnection, artifact_id: UUID, owner_id: UUID) -> dict[str, object]:
    row = await artifacts.get_artifact(conn, artifact_id, owner_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return row
