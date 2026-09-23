"""Read runs and their progress timeline. Layout mode is not stored here."""

from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncConnection

from trading_api.auth import UserDep
from trading_api.dependencies import DatabaseDep
from trading_core.domain.jobs import Run, RunEvent
from trading_core.domain.ta import TAFeature
from trading_core.storage.repositories import conversations, jobs, market

router = APIRouter(prefix="/v1", tags=["runs"])


@router.get("/runs", response_model=list[Run], operation_id="listRuns")
async def list_runs(
    user: UserDep,
    database: DatabaseDep,
    conversation_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[Run]:
    async with database.engine.begin() as conn:
        if conversation_id is not None:
            owned = await conversations.get_conversation(conn, conversation_id, user.id)
            if owned is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
                )
        return await jobs.list_runs(
            conn, conversation_id=conversation_id, owner_id=user.id, limit=limit
        )


@router.get("/runs/{run_id}", response_model=Run, operation_id="getRun")
async def get_run(run_id: UUID, user: UserDep, database: DatabaseDep) -> Run:
    async with database.engine.begin() as conn:
        return await owned_run(conn, run_id, user.id)


@router.get("/runs/{run_id}/events", response_model=list[RunEvent], operation_id="listRunEvents")
async def list_run_events(run_id: UUID, user: UserDep, database: DatabaseDep) -> list[RunEvent]:
    async with database.engine.begin() as conn:
        await owned_run(conn, run_id, user.id)
        return await jobs.list_run_events(conn, run_id)


_CHART_DETECTORS = (
    "volume_profile",
    "fvg",
    "liquidity_sweep",
    "bos",
    "order_block",
    "rsi_divergence",
    "session_levels",
)


@router.get(
    "/runs/{run_id}/features",
    response_model=list[TAFeature],
    operation_id="listRunFeatures",
)
async def list_run_features(
    run_id: UUID,
    user: UserDep,
    database: DatabaseDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 80,
) -> list[TAFeature]:
    """Features whose chart annotations were stored with this run.

    The rows are the calc 1.0.0 features the thesis cites. Levels are not recomputed here.
    """
    async with database.engine.begin() as conn:
        run = await owned_run(conn, run_id, user.id)
        job = await jobs.get_job(conn, run.job_id)
        if job is None:
            return []
        feature_ids = _feature_ids(job.checkpoint.get("feature_ids"))
        rows = await market.list_features(
            conn,
            feature_ids,
            detectors=list(_CHART_DETECTORS),
            limit=limit,
        )
    features: list[TAFeature] = []
    for row in rows:
        features.append(TAFeature.model_validate(_feature_payload(row)))
    return features


def _feature_ids(value: object) -> list[UUID]:
    if not isinstance(value, list):
        return []
    parsed: list[UUID] = []
    for item in value:
        if isinstance(item, str):
            parsed.append(UUID(item))
    return parsed


def _feature_payload(row: dict[str, object]) -> dict[str, object]:
    payload = dict(row)
    for key in ("levels", "parameters", "details", "warnings"):
        raw = payload.get(key)
        if isinstance(raw, str):
            payload[key] = json.loads(raw)
    if payload.get("parameters") is None:
        payload["parameters"] = {}
    if payload.get("details") is None:
        payload["details"] = {}
    if payload.get("warnings") is None:
        payload["warnings"] = []
    return payload


async def owned_run(conn: AsyncConnection, run_id: UUID, owner_id: UUID) -> Run:
    run = await jobs.get_run(conn, run_id)
    if run is None or run.conversation_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    owned = await conversations.get_conversation(conn, run.conversation_id, owner_id)
    if owned is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run
