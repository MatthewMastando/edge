# ruff: noqa: S608
"""Jobs, runs, tool calls, routines and notifications.

Lease acquisition is a single ``UPDATE ... FROM (SELECT ... FOR UPDATE SKIP LOCKED)`` so two
workers cannot take the same job. Moving a job to ``partial`` goes through the state trigger,
which clears ``lease_until`` and makes the row leasable again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID, uuid4

from trading_core.domain.jobs import Job, JobKind, JobState, Run, RunEvent, RunStage, Usage
from trading_core.storage.db import fetch_all, fetch_one
from trading_core.storage.repositories.common import (
    as_datetime,
    as_datetime_or_none,
    as_int,
    as_json_dict,
    as_stages,
    as_str,
    as_str_or_none,
    as_usage,
    as_uuid,
    as_uuid_or_none,
    json_param,
)

if TYPE_CHECKING:
    from datetime import datetime

    from pydantic import JsonValue
    from sqlalchemy.ext.asyncio import AsyncConnection

    from trading_core.domain.common import Provenance

_JOB_COLUMNS = """
id, kind, state, priority, payload, idempotency_key, routine_id, conversation_id,
scheduled_for, scheduled_tz, lease_until, leased_by, checkpoint, attempts, max_attempts,
last_error, created_at, updated_at, started_at, finished_at
"""


def job_from_row(row: dict[str, object]) -> Job:
    return Job(
        id=as_uuid(row["id"]),
        kind=cast("JobKind", as_str(row["kind"])),
        state=cast("JobState", as_str(row["state"])),
        priority=as_int(row["priority"]),
        payload=as_json_dict(row["payload"]),
        idempotency_key=as_str(row["idempotency_key"]),
        routine_id=as_uuid_or_none(row["routine_id"]),
        conversation_id=as_uuid_or_none(row["conversation_id"]),
        scheduled_for=as_datetime(row["scheduled_for"]),
        scheduled_tz=as_str(row["scheduled_tz"], "UTC"),
        lease_until=as_datetime_or_none(row["lease_until"]),
        leased_by=as_str_or_none(row["leased_by"]),
        checkpoint=as_json_dict(row["checkpoint"]),
        attempts=as_int(row["attempts"]),
        max_attempts=as_int(row["max_attempts"], 3),
        last_error=as_str_or_none(row["last_error"]),
        created_at=as_datetime(row["created_at"]),
        updated_at=as_datetime(row["updated_at"]),
        started_at=as_datetime_or_none(row["started_at"]),
        finished_at=as_datetime_or_none(row["finished_at"]),
    )


async def enqueue_job(
    conn: AsyncConnection,
    *,
    kind: JobKind,
    idempotency_key: str,
    payload: dict[str, JsonValue],
    conversation_id: UUID | None = None,
    routine_id: UUID | None = None,
    priority: int = 0,
    scheduled_for: datetime | None = None,
    scheduled_tz: str = "UTC",
    max_attempts: int = 3,
) -> Job:
    row = await fetch_one(
        conn,
        f"""
        insert into jobs (
          kind, idempotency_key, payload, conversation_id, routine_id, priority,
          scheduled_for, scheduled_tz, max_attempts
        ) values (
          :kind, :idempotency_key, cast(:payload as jsonb), :conversation_id, :routine_id,
          :priority, coalesce(:scheduled_for, now()), :scheduled_tz, :max_attempts
        )
        on conflict (idempotency_key) do nothing
        returning {_JOB_COLUMNS}
        """,
        {
            "kind": kind,
            "idempotency_key": idempotency_key,
            "payload": json_param(payload),
            "conversation_id": conversation_id,
            "routine_id": routine_id,
            "priority": priority,
            "scheduled_for": scheduled_for,
            "scheduled_tz": scheduled_tz,
            "max_attempts": max_attempts,
        },
    )
    if row is None:
        existing = await get_job_by_key(conn, idempotency_key)
        if existing is None:
            msg = f"job {idempotency_key!r} disappeared during enqueue"
            raise RuntimeError(msg)
        return existing
    return job_from_row(row)


async def get_job(conn: AsyncConnection, job_id: UUID) -> Job | None:
    row = await fetch_one(conn, f"select {_JOB_COLUMNS} from jobs where id = :id", {"id": job_id})
    return None if row is None else job_from_row(row)


async def get_job_by_key(conn: AsyncConnection, idempotency_key: str) -> Job | None:
    row = await fetch_one(
        conn,
        f"select {_JOB_COLUMNS} from jobs where idempotency_key = :key",
        {"key": idempotency_key},
    )
    return None if row is None else job_from_row(row)


async def requeue_expired(conn: AsyncConnection) -> int:
    """Return expired running leases to ``queued``, or ``failed`` once attempts are spent."""
    rows = await fetch_all(
        conn,
        """
        update jobs
        set state = case when attempts >= max_attempts then 'failed' else 'queued' end,
            last_error = case
              when attempts >= max_attempts then 'lease expired after max attempts'
              else 'lease expired; requeued for resume'
            end
        where state = 'running' and lease_until < now()
        returning id
        """,
    )
    return len(rows)


async def lease_job(
    conn: AsyncConnection,
    *,
    job_id: UUID,
    worker_id: str,
    lease_seconds: int,
) -> Job | None:
    """Lease one known job. Used by the API so a chat run is not stolen by an older row."""
    row = await fetch_one(
        conn,
        f"""
        update jobs
        set state = 'running',
            lease_until = now() + (:lease_seconds * interval '1 second'),
            leased_by = :worker_id
        where id = :id
          and state in ('queued', 'partial')
          and (lease_until is null or lease_until < now())
        returning {_JOB_COLUMNS}
        """,
        {"id": job_id, "worker_id": worker_id, "lease_seconds": lease_seconds},
    )
    return None if row is None else job_from_row(row)


async def lease_next(
    conn: AsyncConnection,
    *,
    worker_id: str,
    lease_seconds: int,
    kinds: list[str],
) -> Job | None:
    if not kinds:
        return None
    row = await fetch_one(
        conn,
        """
        with candidate as (
          select id
          from jobs
          where state in ('queued', 'partial')
            and scheduled_for <= now()
            and (lease_until is null or lease_until < now())
            and kind = any(string_to_array(:kinds, ','))
          order by priority desc, scheduled_for, id
          for update skip locked
          limit 1
        )
        update jobs as j
        set state = 'running',
            lease_until = now() + (:lease_seconds * interval '1 second'),
            leased_by = :worker_id
        from candidate
        where j.id = candidate.id
        returning j.id, j.kind, j.state, j.priority, j.payload, j.idempotency_key,
          j.routine_id, j.conversation_id, j.scheduled_for, j.scheduled_tz, j.lease_until,
          j.leased_by, j.checkpoint, j.attempts, j.max_attempts, j.last_error, j.created_at,
          j.updated_at, j.started_at, j.finished_at
        """,
        {
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
            "kinds": ",".join(kinds),
        },
    )
    return None if row is None else job_from_row(row)


async def save_checkpoint(
    conn: AsyncConnection,
    *,
    job_id: UUID,
    worker_id: str,
    checkpoint: dict[str, JsonValue],
    lease_seconds: int,
) -> bool:
    row = await fetch_one(
        conn,
        """
        update jobs
        set checkpoint = cast(:checkpoint as jsonb),
            lease_until = now() + (:lease_seconds * interval '1 second')
        where id = :id and state = 'running' and leased_by = :worker_id
        returning id
        """,
        {
            "id": job_id,
            "worker_id": worker_id,
            "checkpoint": json_param(checkpoint),
            "lease_seconds": lease_seconds,
        },
    )
    return row is not None


async def set_state(
    conn: AsyncConnection,
    *,
    job_id: UUID,
    worker_id: str,
    state: JobState,
    checkpoint: dict[str, JsonValue],
    last_error: str | None = None,
    scheduled_for: datetime | None = None,
) -> Job | None:
    """Transition a leased job. The trigger clears the lease for ``partial`` and terminal states."""
    row = await fetch_one(
        conn,
        f"""
        update jobs
        set state = :state,
            checkpoint = cast(:checkpoint as jsonb),
            last_error = :last_error,
            scheduled_for = coalesce(:scheduled_for, scheduled_for)
        where id = :id and state = 'running' and leased_by = :worker_id
        returning {_JOB_COLUMNS}
        """,
        {
            "id": job_id,
            "worker_id": worker_id,
            "state": state,
            "checkpoint": json_param(checkpoint),
            "last_error": last_error,
            "scheduled_for": scheduled_for,
        },
    )
    return None if row is None else job_from_row(row)


async def cancel_job(conn: AsyncConnection, job_id: UUID) -> Job | None:
    row = await fetch_one(
        conn,
        f"""
        update jobs
        set state = 'cancelled', last_error = 'cancelled'
        where id = :id and state in ('queued', 'running', 'partial')
        returning {_JOB_COLUMNS}
        """,
        {"id": job_id},
    )
    return None if row is None else job_from_row(row)


async def insert_run(
    conn: AsyncConnection,
    *,
    job_id: UUID,
    conversation_id: UUID | None,
    provider: str,
    provenance: str,
    model: str | None,
    prompt_version: str | None,
    run_id: UUID | None = None,
) -> Run:
    row = await fetch_one(
        conn,
        """
        insert into runs (
          id, job_id, conversation_id, status, provider, model, prompt_version, provenance, usage
        ) values (
          :id, :job_id, :conversation_id, 'running', :provider, :model, :prompt_version,
          :provenance, cast(:usage as jsonb)
        )
        returning id, job_id, conversation_id, artifact_revision_id, status, current_stage,
                  stages_completed, provider, model, prompt_version, provenance, usage,
                  started_at, finished_at, error
        """,
        {
            "id": run_id or uuid4(),
            "job_id": job_id,
            "conversation_id": conversation_id,
            "provider": provider,
            "model": model,
            "prompt_version": prompt_version,
            "provenance": provenance,
            "usage": json_param(Usage().model_dump(mode="json")),
        },
    )
    if row is None:
        msg = "run insert returned no row"
        raise RuntimeError(msg)
    return _run(row)


def _run(row: dict[str, object]) -> Run:
    stage = as_str_or_none(row["current_stage"])
    current = cast("RunStage", stage) if stage is not None else None
    return Run(
        id=as_uuid(row["id"]),
        job_id=as_uuid(row["job_id"]),
        conversation_id=as_uuid_or_none(row["conversation_id"]),
        artifact_revision_id=as_uuid_or_none(row["artifact_revision_id"]),
        status=cast("JobState", as_str(row["status"])),
        current_stage=current,
        stages_completed=as_stages(row["stages_completed"]),
        provider=as_str(row["provider"]),
        model=as_str_or_none(row["model"]),
        prompt_version=as_str_or_none(row["prompt_version"]),
        provenance=cast("Provenance", as_str(row["provenance"])),
        usage=as_usage(row["usage"]),
        started_at=as_datetime(row["started_at"]),
        finished_at=as_datetime_or_none(row["finished_at"]),
        error=as_str_or_none(row["error"]),
    )


async def get_run(conn: AsyncConnection, run_id: UUID) -> Run | None:
    row = await fetch_one(
        conn,
        """
        select id, job_id, conversation_id, artifact_revision_id, status, current_stage,
               stages_completed, provider, model, prompt_version, provenance, usage,
               started_at, finished_at, error
        from runs where id = :id
        """,
        {"id": run_id},
    )
    return None if row is None else _run(row)


async def list_runs(
    conn: AsyncConnection,
    *,
    conversation_id: UUID | None = None,
    owner_id: UUID | None = None,
    limit: int = 50,
) -> list[Run]:
    rows = await fetch_all(
        conn,
        """
        select r.id, r.job_id, r.conversation_id, r.artifact_revision_id, r.status,
               r.current_stage, r.stages_completed, r.provider, r.model, r.prompt_version,
               r.provenance, r.usage, r.started_at, r.finished_at, r.error
        from runs r
        left join conversations c on c.id = r.conversation_id
        where (
            cast(:conversation_id as uuid) is null
            or r.conversation_id = cast(:conversation_id as uuid)
          )
          and (cast(:owner_id as uuid) is null or c.owner_id = cast(:owner_id as uuid))
        order by r.started_at desc
        limit :limit
        """,
        {"conversation_id": conversation_id, "owner_id": owner_id, "limit": limit},
    )
    return [_run(row) for row in rows]


async def update_run(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    status: JobState,
    current_stage: str | None,
    stages_completed: list[str],
    usage: Usage,
    artifact_revision_id: UUID | None = None,
    error: str | None = None,
    finished: bool = False,
) -> None:
    await fetch_one(
        conn,
        """
        update runs
        set status = :status,
            current_stage = :current_stage,
            stages_completed = :stages_completed,
            usage = cast(:usage as jsonb),
            artifact_revision_id = coalesce(:artifact_revision_id, artifact_revision_id),
            error = :error,
            finished_at = case when :finished then coalesce(finished_at, now()) else finished_at end
        where id = :id
        returning id
        """,
        {
            "id": run_id,
            "status": status,
            "current_stage": current_stage,
            "stages_completed": stages_completed,
            "usage": json_param(usage.model_dump(mode="json")),
            "artifact_revision_id": artifact_revision_id,
            "error": error,
            "finished": finished,
        },
    )


async def next_event_sequence(conn: AsyncConnection, run_id: UUID) -> int:
    row = await fetch_one(
        conn,
        "select coalesce(max(sequence), -1) + 1 as sequence from run_events where run_id = :run_id",
        {"run_id": run_id},
    )
    if row is None:
        return 0
    return as_int(row["sequence"])


async def append_run_event(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    sequence: int,
    stage: str | None,
    level: str,
    message: str,
    data: dict[str, JsonValue],
) -> RunEvent:
    row = await fetch_one(
        conn,
        """
        insert into run_events (run_id, sequence, stage, level, message, data)
        values (:run_id, :sequence, :stage, :level, :message, cast(:data as jsonb))
        on conflict (run_id, sequence) do nothing
        returning run_id, sequence, at, stage, level, message, data
        """,
        {
            "run_id": run_id,
            "sequence": sequence,
            "stage": stage,
            "level": level,
            "message": message,
            "data": json_param(data),
        },
    )
    if row is None:
        existing = await fetch_one(
            conn,
            """
            select run_id, sequence, at, stage, level, message, data
            from run_events where run_id = :run_id and sequence = :sequence
            """,
            {"run_id": run_id, "sequence": sequence},
        )
        if existing is None:
            msg = "run event insert conflicted without a row"
            raise RuntimeError(msg)
        row = existing
    return _event(row)


def _event_level(value: str) -> Literal["debug", "info", "warning", "error"]:
    if value == "debug":
        return "debug"
    if value == "warning":
        return "warning"
    if value == "error":
        return "error"
    return "info"


def _event_stage(value: str | None) -> RunStage | None:
    if value is None:
        return None
    for stage in (
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
    ):
        if stage == value:
            return stage
    return None


def _event(row: dict[str, object]) -> RunEvent:
    return RunEvent(
        run_id=as_uuid(row["run_id"]),
        sequence=as_int(row["sequence"]),
        at=as_datetime(row["at"]),
        stage=_event_stage(as_str_or_none(row["stage"])),
        level=_event_level(as_str(row["level"])),
        message=as_str(row["message"]),
        data=as_json_dict(row["data"]),
    )


async def list_run_events(conn: AsyncConnection, run_id: UUID) -> list[RunEvent]:
    rows = await fetch_all(
        conn,
        """
        select run_id, sequence, at, stage, level, message, data
        from run_events
        where run_id = :run_id
        order by sequence
        limit 500
        """,
        {"run_id": run_id},
    )
    return [_event(row) for row in rows]


async def insert_tool_call(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    sequence: int,
    tool_name: str,
    tool_version: str,
    arguments: dict[str, JsonValue],
    output: JsonValue,
    is_error: bool,
    counts_as_external_retrieval: bool,
    duration_ms: int | None,
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into tool_calls (
          run_id, sequence, tool_name, tool_version, arguments, output, is_error,
          counts_as_external_retrieval, finished_at, duration_ms
        ) values (
          :run_id, :sequence, :tool_name, :tool_version, cast(:arguments as jsonb),
          cast(:output as jsonb), :is_error, :counts_as_external_retrieval, now(), :duration_ms
        )
        on conflict (run_id, sequence) do nothing
        returning id
        """,
        {
            "run_id": run_id,
            "sequence": sequence,
            "tool_name": tool_name,
            "tool_version": tool_version,
            "arguments": json_param(arguments),
            "output": json_param(output),
            "is_error": is_error,
            "counts_as_external_retrieval": counts_as_external_retrieval,
            "duration_ms": duration_ms,
        },
    )
    if row is None:
        existing = await fetch_one(
            conn,
            "select id from tool_calls where run_id = :run_id and sequence = :sequence",
            {"run_id": run_id, "sequence": sequence},
        )
        if existing is None:
            msg = "tool call insert conflicted without a row"
            raise RuntimeError(msg)
        return as_uuid(existing["id"])
    return as_uuid(row["id"])


async def insert_notification(
    conn: AsyncConnection,
    *,
    owner_id: UUID | None,
    kind: str,
    severity: str,
    title: str,
    body: str | None,
    run_id: UUID | None,
    artifact_id: UUID | None,
    dedupe_key: str,
) -> UUID | None:
    """Insert once per ``dedupe_key``. A second call returns ``None`` and writes nothing."""
    row = await fetch_one(
        conn,
        """
        insert into notifications (
          owner_id, kind, severity, title, body, run_id, artifact_id, dedupe_key
        ) values (
          :owner_id, :kind, :severity, :title, :body, :run_id, :artifact_id, :dedupe_key
        )
        on conflict (dedupe_key) do nothing
        returning id
        """,
        {
            "owner_id": owner_id,
            "kind": kind,
            "severity": severity,
            "title": title,
            "body": body,
            "run_id": run_id,
            "artifact_id": artifact_id,
            "dedupe_key": dedupe_key,
        },
    )
    if row is None:
        return None
    return as_uuid(row["id"])


async def count_notifications(conn: AsyncConnection, dedupe_key: str) -> int:
    row = await fetch_one(
        conn,
        "select count(*) as n from notifications where dedupe_key = :dedupe_key",
        {"dedupe_key": dedupe_key},
    )
    if row is None:
        return 0
    return as_int(row["n"])


async def insert_routine(
    conn: AsyncConnection,
    *,
    owner_id: UUID,
    name: str,
    kind: str,
    schedule_timezone: str = "America/New_York",
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into routines (owner_id, name, kind, schedule_timezone)
        values (:owner_id, :name, :kind, :schedule_timezone)
        returning id
        """,
        {
            "owner_id": owner_id,
            "name": name,
            "kind": kind,
            "schedule_timezone": schedule_timezone,
        },
    )
    if row is None:
        msg = "routine insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


async def list_routine_names(conn: AsyncConnection, owner_id: UUID) -> list[str]:
    rows = await fetch_all(
        conn,
        "select name from routines where owner_id = :owner_id order by name limit 100",
        {"owner_id": owner_id},
    )
    return [as_str(row["name"]) for row in rows]
