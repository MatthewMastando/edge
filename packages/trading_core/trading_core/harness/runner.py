"""Run a job that this process already leased, and map failures onto the state machine."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from trading_core.domain.jobs import Job, JobState, Usage
from trading_core.harness.budget import BudgetExceededError
from trading_core.harness.errors import LeaseLostError, SuspendWorkflowError, WorkflowPausedError
from trading_core.harness.secrets import redact
from trading_core.harness.workflow import ResearchWorkflow
from trading_core.storage.repositories import jobs
from trading_core.storage.repositories.common import as_uuid

if TYPE_CHECKING:
    from trading_core.harness.deps import WorkflowDeps

log = logging.getLogger("trading_core.harness.runner")


async def run_leased_job(deps: WorkflowDeps, job: Job) -> Job:
    workflow = ResearchWorkflow(deps)
    try:
        await workflow.execute(job)
    except WorkflowPausedError:
        log.info("job %s paused", job.id)
    except SuspendWorkflowError as exc:
        await _mark(deps, job.id, "partial", exc.reason)
    except BudgetExceededError as exc:
        await _mark(deps, job.id, "budget_exceeded", exc.message, notify="budget")
    except LeaseLostError:
        log.warning("lost lease for job %s", job.id)
    except Exception as exc:
        message = redact(str(exc), deps.secrets)
        log.error("job %s failed: %s", job.id, message)
        await _mark(deps, job.id, "failed", message, notify="run_failed")
    async with deps.engine.begin() as conn:
        current = await jobs.get_job(conn, job.id)
    if current is None:
        msg = f"job {job.id} disappeared"
        raise RuntimeError(msg)
    return current


async def _mark(
    deps: WorkflowDeps,
    job_id: UUID,
    state: JobState,
    error: str,
    *,
    notify: str | None = None,
) -> None:
    async with deps.engine.begin() as conn:
        current = await jobs.get_job(conn, job_id)
        if current is None or current.state != "running" or current.leased_by != deps.worker_id:
            return
        updated = await jobs.set_state(
            conn,
            job_id=job_id,
            worker_id=deps.worker_id,
            state=state,
            checkpoint=current.checkpoint,
            last_error=error,
        )
        if updated is None:
            return
        run_raw = current.checkpoint.get("run_id")
        if isinstance(run_raw, str):
            await jobs.update_run(
                conn,
                run_id=UUID(run_raw),
                status=state,
                current_stage=None,
                stages_completed=_stages(current.checkpoint.get("stages_completed")),
                usage=updated_usage(current),
                error=error,
                finished=state != "partial",
            )
        if notify is not None:
            owner_raw = current.payload.get("owner_id")
            owner = as_uuid(owner_raw) if isinstance(owner_raw, str) else None
            await jobs.insert_notification(
                conn,
                owner_id=owner,
                kind=notify,
                severity="error" if notify == "run_failed" else "warning",
                title=f"Research {state.replace('_', ' ')}",
                body=error[:500],
                run_id=UUID(run_raw) if isinstance(run_raw, str) else None,
                artifact_id=None,
                dedupe_key=f"{notify}:{job_id}",
            )


def _stages(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def updated_usage(job: Job) -> Usage:
    raw = job.checkpoint.get("retrievals_used")
    calls = raw if isinstance(raw, int) else 0
    return Usage(retrieval_calls=calls)
