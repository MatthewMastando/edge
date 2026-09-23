"""Chat over SSE. The request leases one research job and streams stage progress."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import Field, JsonValue

from trading_api.auth import UserDep
from trading_api.dependencies import DatabaseDep, FixtureAdapterDep, SettingsDep
from trading_api.runtime import workflow_deps
from trading_core.domain.common import DomainModel, Timeframe
from trading_core.harness.deps import ProgressEvent, ResearchPayload
from trading_core.harness.runner import run_leased_job
from trading_core.harness.secrets import redact, secrets_from_environ
from trading_core.storage.repositories import conversations, jobs

router = APIRouter(prefix="/v1", tags=["chat"])


class ChatRequest(DomainModel):
    message: str = Field(min_length=1, max_length=8000)
    symbol: str = Field(min_length=1, max_length=32)
    conversation_id: UUID | None = None
    timeframe: Timeframe = "5m"
    horizon: str = Field(default="2-5 sessions", min_length=1, max_length=64)
    recording_id: str | None = Field(default=None, max_length=64)
    client_message_id: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[A-Za-z0-9._:-]{1,64}$",
        description="Retries with the same id reuse the existing job instead of starting another.",
    )


def _sse(event: ProgressEvent) -> str:
    return f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"


def _payload_json(payload: ResearchPayload) -> dict[str, JsonValue]:
    raw: object = payload.model_dump(mode="json")
    if not isinstance(raw, dict):
        msg = "chat payload did not serialize"
        raise RuntimeError(msg)
    return cast("dict[str, JsonValue]", raw)


@router.post("/chat", operation_id="postChat")
async def post_chat(
    body: ChatRequest,
    user: UserDep,
    settings: SettingsDep,
    database: DatabaseDep,
    adapter: FixtureAdapterDep,
) -> StreamingResponse:
    conversation_id = await _conversation(database, user.id, body)
    payload = ResearchPayload(
        symbol=body.symbol,
        question=body.message,
        timeframe=body.timeframe,
        horizon=body.horizon,
        recording_id=body.recording_id,
        owner_id=user.id,
    )
    message_key = body.client_message_id or uuid4().hex
    idempotency_key = f"chat:{conversation_id}:{message_key}"
    async with database.engine.begin() as conn:
        existing = await jobs.get_job_by_key(conn, idempotency_key)
        if existing is None:
            await conversations.insert_message(
                conn,
                conversation_id=conversation_id,
                role="user",
                content=body.message,
                metadata={"symbol": body.symbol, "client_message_id": message_key},
            )
        job = existing or await jobs.enqueue_job(
            conn,
            kind="research",
            idempotency_key=idempotency_key,
            payload=_payload_json(payload),
            conversation_id=conversation_id,
        )

    worker_id = f"api-{uuid4().hex[:12]}"

    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()

        async def progress(event: ProgressEvent) -> None:
            await queue.put(event.model_copy(update={"conversation_id": conversation_id}))

        async def work() -> None:
            try:
                async with database.engine.begin() as conn:
                    leased = await jobs.lease_job(
                        conn,
                        job_id=job.id,
                        worker_id=worker_id,
                        lease_seconds=max(int(settings.timeout_seconds), 60),
                    )
                if leased is None:
                    await queue.put(
                        ProgressEvent(
                            event="done",
                            message="existing job was not started again",
                            job_id=job.id,
                            job_state=job.state,
                            conversation_id=conversation_id,
                        )
                    )
                    return
                deps = workflow_deps(
                    settings=settings,
                    database=database,
                    adapter=adapter,
                    worker_id=worker_id,
                )
                deps.owner_id = user.id
                deps.progress = progress
                finished = await run_leased_job(deps, leased)
                if finished.state == "completed":
                    return
                await queue.put(
                    ProgressEvent(
                        event="done" if finished.state == "partial" else "error",
                        message=redact(finished.last_error or finished.state, deps.secrets),
                        job_id=finished.id,
                        job_state=finished.state,
                        conversation_id=conversation_id,
                        run_id=_run_id(finished.checkpoint),
                    )
                )
            except Exception as exc:
                await queue.put(
                    ProgressEvent(
                        event="error",
                        message=redact(str(exc), secrets_from_environ()),
                        job_id=job.id,
                        conversation_id=conversation_id,
                    )
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(work())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield _sse(item)
        finally:
            await task

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _conversation(database: DatabaseDep, owner_id: UUID, body: ChatRequest) -> UUID:
    async with database.engine.begin() as conn:
        if body.conversation_id is not None:
            existing = await conversations.get_conversation(conn, body.conversation_id, owner_id)
            if existing is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
                )
            return body.conversation_id
        return await conversations.insert_conversation(
            conn,
            owner_id=owner_id,
            title=body.symbol,
            context={"symbol": body.symbol},
        )


def _run_id(checkpoint: dict[str, JsonValue]) -> UUID | None:
    raw = checkpoint.get("run_id")
    if not isinstance(raw, str):
        return None
    return UUID(raw)
