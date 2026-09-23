"""Search saved artifacts and conversations. Layout mode is client state."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field

from trading_api.auth import UserDep
from trading_api.dependencies import DatabaseDep
from trading_core.domain.common import DomainModel
from trading_core.storage.repositories import artifacts, conversations
from trading_core.storage.repositories.common import as_datetime, as_str, as_str_or_none, as_uuid

router = APIRouter(prefix="/v1", tags=["search"])


class ArtifactHit(DomainModel):
    id: UUID
    title: str
    kind: str
    updated_at: datetime


class ConversationHit(DomainModel):
    id: UUID
    title: str | None
    updated_at: datetime


class SearchResponse(DomainModel):
    query: str
    artifacts: list[ArtifactHit] = Field(default_factory=list)
    conversations: list[ConversationHit] = Field(default_factory=list)


@router.get("/search", response_model=SearchResponse, operation_id="searchWorkspace")
async def search_workspace(
    user: UserDep,
    database: DatabaseDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResponse:
    async with database.engine.begin() as conn:
        artifact_rows = await artifacts.search_artifacts(conn, user.id, q, limit=limit)
        conversation_rows = await conversations.search_conversations(conn, user.id, q, limit=limit)
    return SearchResponse(
        query=q,
        artifacts=[
            ArtifactHit(
                id=as_uuid(row["id"]),
                title=as_str(row["title"]),
                kind=as_str(row["kind"]),
                updated_at=as_datetime(row["updated_at"]),
            )
            for row in artifact_rows
        ],
        conversations=[
            ConversationHit(
                id=as_uuid(row["id"]),
                title=as_str_or_none(row["title"]),
                updated_at=as_datetime(row["updated_at"]),
            )
            for row in conversation_rows
        ],
    )
