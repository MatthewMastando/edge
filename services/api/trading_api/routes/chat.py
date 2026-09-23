"""Chat over SSE. The request leases one research job and streams stage progress."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import Field, JsonValue

from trading_api.auth import UserDep
from trading_api.dependencies import DatabaseDep, FixtureAdapterDep, SettingsDep
from trading_api.runtime import workflow_deps
from trading_core.domain.common import DomainModel, Timeframe
from trading_core.domain.jobs import JOB_TERMINAL_STATES
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
    dispatch: Literal["inline", "worker"] = Field(
        default="inline",
        description="inline runs the job in this request. worker leaves it queued for the worker.",
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

    if body.dispatch == "worker":

        async def worker_events() -> AsyncIterator[str]:
            async for chunk in _follow(
                database,
                job_id=job.id,
                conversation_id=conversation_id,
                timeout_seconds=max(settings.timeout_seconds, 60),
            ):
                yield chunk

        return StreamingResponse(
            worker_events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def events() -> AsyncIterator[str]:
        async with database.engine.begin() as conn:
            leased = await jobs.lease_job(
                conn,
                job_id=job.id,
                worker_id=worker_id,
                lease_seconds=max(int(settings.timeout_seconds), 60),
            )
        if leased is None:
            async with database.engine.begin() as conn:
                current = await jobs.get_job(conn, job.id)
            if current is not None and current.state not in JOB_TERMINAL_STATES:
                async for chunk in _follow(
                    database,
                    job_id=job.id,
                    conversation_id=conversation_id,
                    timeout_seconds=max(settings.timeout_seconds, 60),
                ):
                    yield chunk
                return
            yield _sse(
                ProgressEvent(
                    event="done",
                    message="existing job was not started again",
                    job_id=job.id,
                    job_state=current.state if current is not None else job.state,
                    conversation_id=conversation_id,
                )
            )
            return

        queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()

        async def progress(event: ProgressEvent) -> None:
            await queue.put(event.model_copy(update={"conversation_id": conversation_id}))

        async def work() -> None:
            try:
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


async def _follow(
    database: DatabaseDep,
    *,
    job_id: UUID,
    conversation_id: UUID,
    timeout_seconds: float,
) -> AsyncIterator[str]:
    """Stream run events until the worker finishes the job this request left queued."""
    seen = -1
    announced = False
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        async with database.engine.begin() as conn:
            current = await jobs.get_job(conn, job_id)
            if current is None:
                yield _sse(
                    ProgressEvent(
                        event="error",
                        message="job disappeared",
                        job_id=job_id,
                        conversation_id=conversation_id,
                    )
                )
                return
            run_id = _run_id(current.checkpoint)
            timeline = await jobs.list_run_events(conn, run_id) if run_id is not None else []
        if not announced:
            announced = True
            yield _sse(
                ProgressEvent(
                    event="progress",
                    message="queued for the worker",
                    job_id=job_id,
                    job_state=current.state,
                    conversation_id=conversation_id,
                    run_id=run_id,
                )
            )
        for item in timeline:
            if item.sequence <= seen:
                continue
            seen = item.sequence
            yield _sse(
                ProgressEvent(
                    event="progress",
                    message=item.message,
                    stage=item.stage,
                    run_id=item.run_id,
                    job_id=job_id,
                    job_state=current.state,
                    conversation_id=conversation_id,
                )
            )
        if current.state in JOB_TERMINAL_STATES:
            thesis = current.checkpoint.get("thesis")
            demonstration = thesis.get("is_demonstration") if isinstance(thesis, dict) else None
            yield _sse(
                ProgressEvent(
                    event="done" if current.state == "completed" else "error",
                    message=current.last_error or current.state,
                    stage="notify" if current.state == "completed" else None,
                    run_id=run_id,
                    job_id=job_id,
                    job_state=current.state,
                    is_demonstration=demonstration if isinstance(demonstration, bool) else None,
                    artifact_id=_optional_uuid(current.checkpoint.get("artifact_id")),
                    conversation_id=conversation_id,
                )
            )
            return
        await asyncio.sleep(0.4)
    yield _sse(
        ProgressEvent(
            event="error",
            message="timed out waiting for the worker",
            job_id=job_id,
            conversation_id=conversation_id,
        )
    )


def _optional_uuid(value: object) -> UUID | None:
    if isinstance(value, str):
        return UUID(value)
    return None


def _run_id(checkpoint: dict[str, JsonValue]) -> UUID | None:
    raw = checkpoint.get("run_id")
    if not isinstance(raw, str):
        return None
    return UUID(raw)
