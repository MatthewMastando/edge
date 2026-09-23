"""One checkpointed research workflow.

resolve instrument -> capture snapshot -> deterministic TA -> sourced context ->
bounded tool loop -> critique -> validation -> one repair -> persist -> notify.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, NoReturn, cast
from uuid import UUID, uuid4

from pydantic import JsonValue, ValidationError

from trading_core.automation.alerts import decide_alert
from trading_core.automation.hypotheses import freeze_thesis
from trading_core.data.adapter import BarsRequest, TradesRequest, UnknownSymbolError
from trading_core.domain.jobs import Job, JobState, RunStage, Usage
from trading_core.domain.market import BarSeries, MarketSnapshot, TradeBatch
from trading_core.domain.ta import DetectorName, TAEvent, TAFeature, TAFeatureTransition
from trading_core.domain.thesis import Thesis
from trading_core.harness.annotations import (
    SavedCalculation,
    annotation_id_for,
    calculations_from_rows,
    stamp_feature,
)
from trading_core.harness.budget import BudgetExceededError, BudgetService
from trading_core.harness.checkpoints import ResearchCheckpoint, dump_checkpoint
from trading_core.harness.deps import (
    CORE_INSTRUCTIONS,
    PROMPT_VERSION,
    STAGE_ORDER,
    ProgressEvent,
    ResearchPayload,
    WorkflowDeps,
)
from trading_core.harness.errors import LeaseLostError, WorkflowPausedError
from trading_core.harness.limits import estimate_tokens
from trading_core.harness.provider import Message, ModelRequest, ModelResponse, ToolResult
from trading_core.harness.secrets import redact
from trading_core.harness.thesis_builder import assemble_thesis
from trading_core.harness.tools import ToolRegistry, ToolSession, build_research_registry
from trading_core.harness.validation import attach_validation, repair_thesis, validate_thesis
from trading_core.storage.base import ObjectNotFoundError
from trading_core.storage.repositories import (
    artifacts,
    automation,
    jobs,
    market,
    reference,
    sources,
)
from trading_core.storage.repositories.common import as_str, as_uuid
from trading_core.storage.repositories.conversations import insert_assistant_once
from trading_core.storage.schemas import (
    bars_to_table,
    table_to_bars,
    table_to_trades,
    trades_to_table,
)
from trading_core.ta import (
    CALC_VERSION,
    Detector,
    DetectorInput,
    DetectorRegistry,
    InsufficientDataError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from trading_core.domain.common import AssetClass, Provenance

log = logging.getLogger("trading_core.harness.workflow")

_DETECTORS = (
    "volume_profile",
    "fvg",
    "liquidity_sweep",
    "bos",
    "order_block",
    "rsi_divergence",
)

_ASSET_CLASSES = {
    "futures",
    "equity",
    "etf",
    "crypto_spot",
    "crypto_futures",
    "event_contract",
}


class ResearchWorkflow:
    def __init__(self, deps: WorkflowDeps) -> None:
        self._deps = deps
        self._deadline = 0.0
        self._lease_lost = asyncio.Event()

    async def execute(self, job: Job) -> None:
        self._deadline = time.monotonic() + self._deps.limits.timeout_seconds
        self._lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(self._hold_lease(job.id))
        try:
            await self._run_stages(job)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _hold_lease(self, job_id: UUID) -> None:
        """Keep the lease alive while a stage is awaiting I/O.

        A second worker can lease the row once ``lease_until`` passes. Extending it here
        stops that worker from starting a second run of the same job.
        """
        interval = max(1.0, self._deps.lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                async with self._deps.engine.begin() as conn:
                    held = await jobs.extend_lease(
                        conn,
                        job_id=job_id,
                        worker_id=self._deps.worker_id,
                        lease_seconds=self._deps.lease_seconds,
                    )
            except Exception:
                log.warning("lease heartbeat failed for job %s", job_id)
                continue
            if not held:
                self._lease_lost.set()
                return

    def _require_lease(self, job: Job) -> None:
        if self._lease_lost.is_set():
            raise LeaseLostError(str(job.id))

    async def _run_stages(self, job: Job) -> None:
        payload = ResearchPayload.model_validate(job.payload)
        checkpoint = ResearchCheckpoint.model_validate(job.checkpoint)
        checkpoint = await self._ensure_run(job, checkpoint)
        if set(STAGE_ORDER).issubset(checkpoint.stages_completed):
            await self._finish(job, checkpoint)
            return
        try:
            for stage in STAGE_ORDER:
                self._require_lease(job)
                if stage in checkpoint.stages_completed:
                    continue
                if self._expired():
                    await self._pause(job, checkpoint, "timeout")
                checkpoint = await self._dispatch(stage, job, checkpoint, payload)
                if stage not in checkpoint.stages_completed:
                    completed = [*checkpoint.stages_completed, cast("RunStage", stage)]
                    checkpoint = checkpoint.model_copy(update={"stages_completed": completed})
                    await self._save(job, checkpoint)
                if self._deps.after_stage is not None:
                    await self._deps.after_stage(stage, checkpoint)
        except WorkflowPausedError:
            return
        await self._finish(job, checkpoint)

    async def _dispatch(  # noqa: PLR0911
        self,
        stage: str,
        job: Job,
        checkpoint: ResearchCheckpoint,
        payload: ResearchPayload,
    ) -> ResearchCheckpoint:
        checkpoint = await self._note(job, checkpoint, stage, f"stage {stage} started")
        if stage == "resolve_instrument":
            return await self._resolve(job, checkpoint, payload)
        if stage == "capture_snapshot":
            return await self._capture(job, checkpoint, payload)
        if stage == "deterministic_ta":
            return await self._ta(checkpoint, payload)
        if stage == "gather_context":
            return await self._gather(job, checkpoint, payload)
        if stage == "synthesize":
            return await self._synthesize(job, checkpoint, payload)
        if stage == "critique":
            return await self._critique(checkpoint, payload)
        if stage == "validate":
            return await self._validate(checkpoint)
        if stage == "repair":
            return await self._repair(job, checkpoint, payload)
        if stage == "persist":
            return await self._persist(job, checkpoint, payload)
        if stage == "notify":
            return await self._notify(job, checkpoint, payload)
        msg = f"unknown stage {stage}"
        raise RuntimeError(msg)

    async def _resolve(
        self, job: Job, checkpoint: ResearchCheckpoint, payload: ResearchPayload
    ) -> ResearchCheckpoint:
        try:
            resolved = await self._deps.adapter.resolve(payload.symbol)
        except UnknownSymbolError as exc:
            msg = f"unknown symbol {payload.symbol}"
            raise RuntimeError(msg) from exc
        async with self._deps.engine.begin() as conn:
            await reference.upsert_session_calendar(conn, resolved.calendar)
            instrument = await reference.upsert_instrument(conn, resolved.instrument)
            contract_code = None
            tick_value = instrument.tick_value
            point_value = instrument.multiplier
            if resolved.contract is not None:
                contract = resolved.contract.model_copy(update={"instrument_id": instrument.id})
                stored = await reference.upsert_futures_contract(conn, contract)
                contract_code = stored.contract_code
                tick_value = stored.tick_value
                point_value = stored.point_multiplier
        log.info("resolved %s for job %s", payload.symbol, job.id)
        return checkpoint.model_copy(
            update={
                "symbol": payload.symbol,
                "instrument_id": instrument.id,
                "contract_code": contract_code,
                "venue": instrument.venue,
                "asset_class": instrument.asset_class,
                "calendar_id": resolved.calendar.id,
                "calendar_version": resolved.calendar.version,
                "tick_value": format(tick_value, "f"),
                "point_value": format(point_value, "f"),
            }
        )

    async def _capture(
        self, job: Job, checkpoint: ResearchCheckpoint, payload: ResearchPayload
    ) -> ResearchCheckpoint:
        if checkpoint.bars_snapshot_id is not None:
            return checkpoint
        await self._record_market_data(job, checkpoint)
        instrument_id = _required_uuid(checkpoint.instrument_id, "instrument")
        bars = await self._deps.adapter.get_bars(
            BarsRequest(symbol=payload.symbol, timeframe=payload.timeframe, limit=5000)
        )
        if not bars.bars:
            msg = f"no bars for {payload.symbol}"
            raise RuntimeError(msg)
        try:
            trades = await self._deps.adapter.get_trades(
                TradesRequest(symbol=payload.symbol, limit=200_000)
            )
        except UnknownSymbolError:
            trades = None
        bar_table = bars_to_table(bars.bars)
        bar_key = (
            f"runs/{instrument_id}/{bars.data_revision}/"
            f"{payload.symbol}-{payload.timeframe}-bars.parquet"
        )
        stored_bars = self._deps.store.put_table(bar_key, bar_table)
        last = bars.bars[-1]
        first = bars.bars[0]
        coverage = self._deps.adapter.capabilities.coverage_note
        bar_snapshot = MarketSnapshot(
            id=uuid4(),
            instrument_id=instrument_id,
            contract_code=checkpoint.contract_code,
            timeframe=payload.timeframe,
            kind="bars",
            range_start=first.origin_time,
            range_end=last.origin_time,
            as_of=last.origin_time,
            as_of_tz=last.origin_tz,
            provider=self._deps.adapter.capabilities.provider,
            provenance=bars.provenance,
            data_revision=bars.data_revision,
            storage_key=bar_key,
            row_count=stored_bars.row_count,
            content_hash=stored_bars.content_hash,
            coverage_note=coverage,
        )
        snapshot_ids = list(checkpoint.snapshot_ids)
        async with self._deps.engine.begin() as conn:
            bars_id = await market.insert_snapshot(
                conn, bar_snapshot, backend=self._deps.store.backend
            )
            snapshot_ids.append(bars_id)
            if trades is not None:
                trade_key = (
                    f"runs/{instrument_id}/{bars.data_revision}/{payload.symbol}-trades.parquet"
                )
                trade_table = trades_to_table(trades.trades)
                stored_trades = self._deps.store.put_table(trade_key, trade_table)
                trade_end = trades.trades[-1].trade_time if trades.trades else last.origin_time
                trade_start = trades.trades[0].trade_time if trades.trades else first.origin_time
                trade_snapshot = MarketSnapshot(
                    id=uuid4(),
                    instrument_id=instrument_id,
                    contract_code=checkpoint.contract_code,
                    timeframe=None,
                    kind="trades",
                    range_start=trade_start,
                    range_end=trade_end,
                    as_of=last.origin_time,
                    as_of_tz=last.origin_tz,
                    provider=self._deps.adapter.capabilities.provider,
                    provenance=trades.provenance,
                    data_revision=trades.data_revision,
                    storage_key=trade_key,
                    row_count=stored_trades.row_count,
                    content_hash=stored_trades.content_hash,
                    coverage_note=coverage,
                )
                snapshot_ids.append(
                    await market.insert_snapshot(
                        conn, trade_snapshot, backend=self._deps.store.backend
                    )
                )
        return checkpoint.model_copy(
            update={
                "bars_snapshot_id": bars_id,
                "snapshot_ids": _unique_ids(snapshot_ids),
                "data_revision": bars.data_revision,
                "as_of": last.origin_time.isoformat(),
            }
        )

    async def _ta(
        self, checkpoint: ResearchCheckpoint, payload: ResearchPayload
    ) -> ResearchCheckpoint:
        instrument_id = _required_uuid(checkpoint.instrument_id, "instrument")
        snapshot_id = _required_uuid(checkpoint.bars_snapshot_id, "snapshot")
        warnings = list(checkpoint.warnings)
        stubs: list[str] = []
        summaries = list(checkpoint.feature_summaries)
        feature_ids = list(checkpoint.feature_ids)
        resolved = await self._deps.adapter.resolve(payload.symbol)
        bars, trades = await self._snapshot_series(checkpoint, instrument_id, payload)
        detector_input = DetectorInput(
            instrument=resolved.instrument.model_copy(update={"id": instrument_id}),
            contract=(
                None
                if resolved.contract is None
                else resolved.contract.model_copy(update={"instrument_id": instrument_id})
            ),
            calendar=resolved.calendar,
            session="current_session",
            bars=bars,
            trades=trades,
            snapshot_id=snapshot_id,
        )
        async with self._deps.engine.begin() as conn:
            for name in _DETECTORS:
                detector = _lookup(self._deps.detectors, name)
                if detector is None:
                    stubs.append(name)
                    warnings.append(f"detector {name} is a stub; no features emitted")
                    continue
                try:
                    output = detector.run(
                        detector_input.model_copy(
                            update={"parameters": detector.default_parameters()}
                        )
                    )
                except InsufficientDataError as exc:
                    warnings.append(f"{name}: {exc}")
                    continue
                stored_ids, stored_summaries = await _persist_output(
                    conn,
                    features=output.features,
                    events=output.events,
                    transitions=output.transitions,
                    instrument_id=instrument_id,
                    snapshot_id=snapshot_id,
                    contract_code=checkpoint.contract_code,
                    data_revision=checkpoint.data_revision,
                )
                feature_ids.extend(stored_ids)
                summaries.extend(stored_summaries)
            for raw in payload.fixture_features:
                try:
                    feature = TAFeature.model_validate(raw)
                except ValidationError as exc:
                    warnings.append(f"ignored fixture feature: {exc.error_count()} errors")
                    continue
                feature = feature.model_copy(
                    update={
                        "instrument_id": instrument_id,
                        "snapshot_id": snapshot_id,
                        "contract_code": checkpoint.contract_code,
                        "data_revision": checkpoint.data_revision or feature.data_revision,
                        "provenance": "fixture",
                    }
                )
                stamped = stamp_feature(feature)
                await market.insert_feature(conn, stamped)
                feature_ids.append(stamped.id)
                summaries.append(_summary(stamped))
        log.info(
            "ta %s features=%d stubs=%s",
            payload.symbol,
            len(feature_ids),
            ",".join(stubs) or "none",
        )
        return checkpoint.model_copy(
            update={
                "feature_ids": _unique_ids(feature_ids),
                "feature_summaries": summaries,
                "stub_detectors": stubs,
                "warnings": warnings,
            }
        )

    async def _snapshot_series(
        self, checkpoint: ResearchCheckpoint, instrument_id: UUID, payload: ResearchPayload
    ) -> tuple[BarSeries, TradeBatch | None]:
        """Run TA on the captured parquet, not a second read of the adapter."""
        async with self._deps.engine.begin() as conn:
            rows = await market.list_snapshots(conn, checkpoint.snapshot_ids)
        bars_id = _required_uuid(checkpoint.bars_snapshot_id, "snapshot")
        bar_row = next((row for row in rows if as_uuid(row["id"]) == bars_id), None)
        if bar_row is None:
            msg = "bar snapshot row is missing"
            raise RuntimeError(msg)
        bar_key = as_str(bar_row["storage_key"])
        try:
            loaded = table_to_bars(self._deps.store.get_table(bar_key))
        except ObjectNotFoundError as exc:
            msg = f"bar snapshot {bar_key} is not in the object store"
            raise RuntimeError(msg) from exc
        if not loaded:
            msg = f"bar snapshot {bar_key} is empty"
            raise RuntimeError(msg)
        revision = loaded[0].data_revision
        if checkpoint.data_revision is not None and revision != checkpoint.data_revision:
            msg = "bar snapshot data revision does not match the checkpoint"
            raise RuntimeError(msg)
        series = BarSeries(
            instrument_id=instrument_id,
            contract_code=checkpoint.contract_code,
            timeframe=payload.timeframe,
            data_revision=revision,
            provenance=loaded[0].provenance,
            bars=[bar.model_copy(update={"instrument_id": instrument_id}) for bar in loaded],
        )
        trade_row = next((row for row in rows if row.get("kind") == "trades"), None)
        if trade_row is None:
            return series, None
        trade_key = as_str(trade_row["storage_key"])
        try:
            trades = table_to_trades(self._deps.store.get_table(trade_key))
        except ObjectNotFoundError as exc:
            msg = f"trade snapshot {trade_key} is not in the object store"
            raise RuntimeError(msg) from exc
        if trades and trades[0].data_revision != revision:
            msg = "trade snapshot data revision does not match the bar snapshot"
            raise RuntimeError(msg)
        batch = TradeBatch(
            instrument_id=instrument_id,
            contract_code=checkpoint.contract_code,
            data_revision=revision,
            provenance=trades[0].provenance if trades else series.provenance,
            trades=[trade.model_copy(update={"instrument_id": instrument_id}) for trade in trades],
        )
        return series, batch

    async def _gather(
        self, job: Job, checkpoint: ResearchCheckpoint, payload: ResearchPayload
    ) -> ResearchCheckpoint:
        if checkpoint.excerpt_ids:
            return checkpoint
        if payload.tier == "brief":
            return checkpoint.model_copy(
                update={
                    "warnings": [
                        *checkpoint.warnings,
                        "brief tier: web retrieval skipped",
                    ],
                }
            )
        if checkpoint.retrievals_used >= self._deps.limits.max_external_retrievals:
            return checkpoint.model_copy(
                update={
                    "partial_research": True,
                    "stop_reason": "retrieval_cap",
                    "warnings": [
                        *checkpoint.warnings,
                        "external retrieval cap reached before context",
                    ],
                }
            )
        budget = self._budget(checkpoint, job)
        reservation = await budget.reserve(
            category="search",
            provider="fixture",
            estimate=self._deps.limits.retrieval_reserve_usd,
            unit_type="calls",
        )
        try:
            now = datetime.now(UTC)
            text = (
                f"Fixture context for {payload.symbol}. No live macro, calendar, or news source "
                "was retrieved. This excerpt is demonstration context, not a market fact."
            )
            async with self._deps.engine.begin() as conn:
                source_id = await sources.insert_source(
                    conn,
                    kind="web_page",
                    url=None,
                    title=f"Fixture context {payload.symbol}",
                    publisher="fixture",
                    published_at=None,
                    retrieved_at=now,
                    provider="fixture",
                    provenance="fixture",
                )
                excerpt = await sources.insert_excerpt(
                    conn,
                    source_id=source_id,
                    text=text,
                    published_at=None,
                    retrieved_at=now,
                    provenance="fixture",
                    kind="web_page",
                )
        finally:
            await budget.reconcile(reservation, Decimal(0))
        return checkpoint.model_copy(
            update={
                "source_ids": [source_id],
                "excerpt_ids": [excerpt.id],
                "retrievals_used": checkpoint.retrievals_used + 1,
            }
        )

    async def _synthesize(
        self, job: Job, checkpoint: ResearchCheckpoint, payload: ResearchPayload
    ) -> ResearchCheckpoint:
        if checkpoint.thesis is not None:
            return checkpoint
        run_id = _required_uuid(checkpoint.run_id, "run")
        registry = build_research_registry(include_web=payload.tier != "brief")
        budget = self._budget(checkpoint, job)
        session = ToolSession(
            deps=self._deps,
            budget=budget,
            run_id=run_id,
            job_id=job.id,
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            feature_summaries=list(checkpoint.feature_summaries),
            stub_detectors=set(checkpoint.stub_detectors),
            source_ids=list(checkpoint.source_ids),
            excerpt_ids=list(checkpoint.excerpt_ids),
            retrievals=checkpoint.retrievals_used,
            tool_sequence=checkpoint.tool_sequence,
        )
        packet, truncated = await self._packet(checkpoint, payload)
        if truncated:
            checkpoint = checkpoint.model_copy(
                update={
                    "partial_research": True,
                    "stop_reason": checkpoint.stop_reason or "evidence_token_cap",
                    "warnings": [
                        *checkpoint.warnings,
                        "evidence pack truncated at the token cap",
                    ],
                }
            )
        request = ModelRequest(
            instructions=CORE_INSTRUCTIONS,
            messages=[Message(role="user", content=packet)],
            tools=registry.specs(),
            model=self._deps.model,
            recording_id=payload.recording_id,
        )
        response, checkpoint = await self._model_rounds(
            job,
            checkpoint,
            request,
            budget,
            registry,
            session,
            estimate_tokens(packet),
        )
        raw_json = response.output_json if response is not None else None
        model_json = raw_json if isinstance(raw_json, dict) else {}
        model_text = response.output_text if response is not None else None
        provenance = _provenance(response.provenance if response is not None else "recorded")
        demonstration = provenance != "live" or (response is not None and response.is_demonstration)
        thesis = assemble_thesis(
            run_id=run_id,
            instrument_id=_required_uuid(checkpoint.instrument_id, "instrument"),
            symbol=payload.symbol,
            asset_class=_asset(checkpoint.asset_class),
            contract_code=checkpoint.contract_code,
            venue=checkpoint.venue or "unknown",
            horizon=payload.horizon,
            as_of=_as_of(checkpoint.as_of),
            feature_rows=checkpoint.feature_summaries,
            model_json=model_json,
            model_text=model_text,
            provider=self._deps.provider.name,
            model=self._deps.model,
            provenance=provenance,
            is_demonstration=demonstration,
            stub_detectors=checkpoint.stub_detectors,
            warnings=checkpoint.warnings,
            secrets=self._deps.secrets,
        )
        dumped = cast("dict[str, JsonValue]", thesis.model_dump(mode="json"))
        return checkpoint.model_copy(
            update={
                "thesis": dumped,
                "retrievals_used": session.retrievals,
                "tool_sequence": session.tool_sequence,
                "source_ids": session.source_ids,
                "excerpt_ids": session.excerpt_ids,
            }
        )

    async def _model_rounds(
        self,
        job: Job,
        checkpoint: ResearchCheckpoint,
        request: ModelRequest,
        budget: BudgetService,
        registry: ToolRegistry,
        session: ToolSession,
        evidence_tokens: int,
    ) -> tuple[ModelResponse | None, ResearchCheckpoint]:
        """Stop or return a partial thesis when a later reserve hits the monthly ceiling."""
        response: ModelResponse | None = None
        tool_results: list[ToolResult] = []
        for _iteration in range(self._deps.limits.max_model_iterations):
            self._require_lease(job)
            if self._expired():
                await self._pause(job, checkpoint, "timeout")
            try:
                reservation = await budget.reserve(
                    category="llm",
                    provider=self._deps.provider.name,
                    estimate=self._deps.limits.llm_reserve_usd,
                    unit_type="calls",
                )
            except BudgetExceededError:
                if response is None:
                    raise
                return response, _mark_partial(checkpoint, "budget_ceiling")
            try:
                response = await self._deps.provider.respond(
                    request.model_copy(update={"tool_results": tool_results})
                )
            except Exception:
                await budget.reconcile(reservation, Decimal(0))
                raise
            actual = response.usage.actual_cost_usd or Decimal(0)
            await budget.reconcile(reservation, actual)
            if not response.tool_calls:
                return response, checkpoint
            added = await self._apply_tool_calls(
                job, session, registry, response, tool_results, evidence_tokens
            )
            if added is None:
                return response, _mark_partial(checkpoint, "evidence_token_cap")
            evidence_tokens += added
            if session.retrievals >= self._deps.limits.max_external_retrievals:
                return response, _mark_partial(checkpoint, "retrieval_cap")
        return response, _mark_partial(checkpoint, "iteration_cap")

    async def _apply_tool_calls(
        self,
        job: Job,
        session: ToolSession,
        registry: ToolRegistry,
        response: ModelResponse,
        tool_results: list[ToolResult],
        evidence_tokens: int,
    ) -> int | None:
        added = 0
        for call in response.tool_calls:
            self._require_lease(job)
            result = await registry.invoke(session, call)
            addition = estimate_tokens("" if result.output is None else str(result.output))
            if evidence_tokens + added + addition > self._deps.limits.max_evidence_tokens:
                return None
            added += addition
            tool_results.append(result)
        return added

    async def _critique(
        self, checkpoint: ResearchCheckpoint, payload: ResearchPayload
    ) -> ResearchCheckpoint:
        notes = list(checkpoint.warnings)
        if not checkpoint.feature_ids:
            notes.append("critique: no computed features were available")
        opposing = (checkpoint.thesis or {}).get("opposing_evidence")
        if not isinstance(opposing, list) or not opposing:
            notes.append("critique: seek opposing evidence; none was cited")
        return checkpoint.model_copy(update={"warnings": notes, "symbol": payload.symbol})

    async def _validate(self, checkpoint: ResearchCheckpoint) -> ResearchCheckpoint:
        thesis = _thesis(checkpoint)
        (
            known_features,
            levels,
            known_sources,
            known_excerpts,
            calculations,
        ) = await self._validation_inputs(checkpoint)
        result = validate_thesis(
            thesis,
            known_feature_ids=known_features,
            feature_levels=levels,
            known_source_ids=known_sources,
            known_excerpt_ids=known_excerpts,
            tick_value=_decimal(checkpoint.tick_value),
            point_value=_decimal(checkpoint.point_value),
            repair_attempted=checkpoint.repair_attempted,
            calculations=calculations,
        )
        updated = attach_validation(thesis, result)
        dumped = cast("dict[str, JsonValue]", updated.model_dump(mode="json"))
        return checkpoint.model_copy(
            update={
                "thesis": dumped,
                "validation_passed": result.passed,
            }
        )

    async def _repair(
        self, job: Job, checkpoint: ResearchCheckpoint, payload: ResearchPayload
    ) -> ResearchCheckpoint:
        del job, payload
        if checkpoint.validation_passed or checkpoint.repair_attempted:
            return checkpoint
        if self._deps.limits.max_repair_attempts < 1:
            return checkpoint.model_copy(
                update={
                    "partial_research": True,
                    "stop_reason": checkpoint.stop_reason or "validation",
                }
            )
        thesis = _thesis(checkpoint)
        (
            known_features,
            levels,
            known_sources,
            known_excerpts,
            calculations,
        ) = await self._validation_inputs(checkpoint)
        repaired = repair_thesis(
            thesis,
            known_feature_ids=known_features,
            feature_levels=levels,
            known_source_ids=known_sources,
            known_excerpt_ids=known_excerpts,
            tick_value=_decimal(checkpoint.tick_value),
            point_value=_decimal(checkpoint.point_value),
        )
        result = validate_thesis(
            repaired,
            known_feature_ids=known_features,
            feature_levels=levels,
            known_source_ids=known_sources,
            known_excerpt_ids=known_excerpts,
            tick_value=_decimal(checkpoint.tick_value),
            point_value=_decimal(checkpoint.point_value),
            repair_attempted=True,
            calculations=calculations,
        )
        updated = attach_validation(repaired, result)
        dumped = cast("dict[str, JsonValue]", updated.model_dump(mode="json"))
        partial = not result.passed
        return checkpoint.model_copy(
            update={
                "thesis": dumped,
                "validation_passed": result.passed,
                "repair_attempted": True,
                "partial_research": checkpoint.partial_research or partial,
                "stop_reason": checkpoint.stop_reason or (None if result.passed else "validation"),
            }
        )

    async def _persist(
        self, job: Job, checkpoint: ResearchCheckpoint, payload: ResearchPayload
    ) -> ResearchCheckpoint:
        if checkpoint.revision_id is not None:
            completed = _with_stage(checkpoint, "persist")
            return completed
        thesis = _thesis(checkpoint)
        owner_id = payload.owner_id or self._deps.owner_id
        if owner_id is None:
            msg = "research job has no owner"
            raise RuntimeError(msg)
        run_id = _required_uuid(checkpoint.run_id, "run")
        structured = cast("dict[str, JsonValue]", thesis.model_dump(mode="json"))
        async with self._deps.engine.begin() as conn:
            existing = await artifacts.generated_revision_for_run(conn, run_id)
            if existing is not None:
                revision_id, artifact_id = existing
            else:
                stored_artifact_id = checkpoint.artifact_id
                if stored_artifact_id is None:
                    stored_artifact_id = await artifacts.insert_artifact(
                        conn,
                        owner_id=owner_id,
                        conversation_id=job.conversation_id,
                        kind="thesis",
                        title=f"{payload.symbol} research",
                        instrument_id=thesis.instrument_id,
                        contract_code=thesis.contract_code,
                        tags=["research", payload.symbol]
                        + (["demonstration"] if thesis.is_demonstration else []),
                    )
                artifact_id = stored_artifact_id
                revision_id, _number = await artifacts.insert_revision(
                    conn,
                    artifact_id=artifact_id,
                    parent_revision_id=None,
                    run_id=run_id,
                    structured=structured,
                    presentation_markdown=thesis.presentation_markdown,
                    change_kind="generated",
                    created_by="agent",
                    is_demonstration=thesis.is_demonstration,
                    provenance=thesis.provenance,
                )
            await artifacts.set_current_revision(conn, artifact_id, revision_id)
            await freeze_thesis(conn, thesis, revision_id)
            await jobs.update_run(
                conn,
                run_id=run_id,
                status="running",
                current_stage="persist",
                stages_completed=[*checkpoint.stages_completed, "persist"],
                usage=_usage(checkpoint),
                artifact_revision_id=revision_id,
            )
            updated = checkpoint.model_copy(
                update={
                    "artifact_id": artifact_id,
                    "revision_id": revision_id,
                    "stages_completed": _with_stage(checkpoint, "persist").stages_completed,
                }
            )
            saved = await jobs.save_checkpoint(
                conn,
                job_id=job.id,
                worker_id=self._deps.worker_id,
                checkpoint=dump_checkpoint(updated),
                lease_seconds=self._deps.lease_seconds,
            )
            _raise_if_lease_lost(saved, job.id)
        return updated

    async def _notify(
        self, job: Job, checkpoint: ResearchCheckpoint, payload: ResearchPayload
    ) -> ResearchCheckpoint:
        if checkpoint.notified:
            return _with_stage(checkpoint, "notify")
        thesis = _thesis(checkpoint)
        owner_id = payload.owner_id or self._deps.owner_id
        run_id = _required_uuid(checkpoint.run_id, "run")
        label = "Demonstration" if thesis.is_demonstration else "Research"
        partial = " partial" if checkpoint.partial_research else ""
        async with self._deps.engine.begin() as conn:
            prior = None
            if checkpoint.revision_id is not None:
                prior = await automation.previous_structured(
                    conn,
                    instrument_id=thesis.instrument_id,
                    revision_id=checkpoint.revision_id,
                )
            kind = decide_alert(cast("dict[str, JsonValue]", thesis.model_dump(mode="json")), prior)
            if kind is not None:
                await jobs.insert_notification(
                    conn,
                    owner_id=owner_id,
                    kind=kind,
                    severity="info",
                    title=f"{label}{partial} research: {payload.symbol}",
                    body=thesis.presentation_markdown[:500],
                    run_id=run_id,
                    artifact_id=checkpoint.artifact_id,
                    dedupe_key=f"research:{job.id}:{kind}",
                )
            await insert_assistant_once(
                conn,
                conversation_id=job.conversation_id,
                run_id=run_id,
                content=thesis.presentation_markdown,
                is_demonstration=thesis.is_demonstration,
            )
            updated = _with_stage(checkpoint.model_copy(update={"notified": True}), "notify")
            saved = await jobs.save_checkpoint(
                conn,
                job_id=job.id,
                worker_id=self._deps.worker_id,
                checkpoint=dump_checkpoint(updated),
                lease_seconds=self._deps.lease_seconds,
            )
            _raise_if_lease_lost(saved, job.id)
        if self._deps.progress is not None:
            await self._deps.progress(
                ProgressEvent(
                    event="message",
                    message=thesis.presentation_markdown,
                    stage="notify",
                    run_id=run_id,
                    job_id=job.id,
                    is_demonstration=thesis.is_demonstration,
                    artifact_id=checkpoint.artifact_id,
                )
            )
        return updated

    async def _packet(
        self, checkpoint: ResearchCheckpoint, payload: ResearchPayload
    ) -> tuple[str, bool]:
        lines = [
            f"Question: {redact(payload.question, self._deps.secrets)}",
            f"Symbol: {payload.symbol}",
            f"Contract: {checkpoint.contract_code or 'n/a'}",
            f"Venue: {checkpoint.venue or 'n/a'}",
            f"Horizon: {payload.horizon}",
            f"As of: {checkpoint.as_of or 'unknown'}",
            f"Data revision: {checkpoint.data_revision or 'unknown'}",
            "Computed features:",
        ]
        if checkpoint.feature_summaries:
            for summary in checkpoint.feature_summaries:
                lines.append(redact(str(summary), self._deps.secrets))
        else:
            lines.append("none")
        lines.append("Stub detectors: " + (", ".join(checkpoint.stub_detectors) or "none"))
        lines.append("Source excerpts:")
        used = 0
        truncated = False
        limit = self._deps.limits.max_evidence_tokens
        async with self._deps.engine.begin() as conn:
            for excerpt_id in checkpoint.excerpt_ids:
                text = await sources.get_excerpt_text(conn, excerpt_id)
                if not text:
                    continue
                tokens = estimate_tokens(text)
                if used + tokens > limit:
                    lines.append("evidence pack truncated at the token cap")
                    truncated = True
                    break
                used += tokens
                lines.append(f"[{excerpt_id}] {redact(text, self._deps.secrets)}")
        if len(checkpoint.excerpt_ids) == 0:
            lines.append("none")
        lines.append("Do not invent prices, feature ids, or a trading edge.")
        return "\n".join(lines), truncated

    async def _validation_inputs(
        self, checkpoint: ResearchCheckpoint
    ) -> tuple[
        set[UUID],
        dict[UUID, set[Decimal]],
        set[UUID],
        set[UUID],
        dict[UUID, SavedCalculation],
    ]:
        async with self._deps.engine.begin() as conn:
            known_features = await market.list_feature_ids(conn, checkpoint.feature_ids)
            levels = await market.feature_levels(conn, checkpoint.feature_ids)
            known_sources = await sources.existing_source_ids(conn, checkpoint.source_ids)
            known_excerpts = await sources.existing_excerpt_ids(conn, checkpoint.excerpt_ids)
            rows = await market.feature_calculation_rows(conn, checkpoint.feature_ids)
        return (
            known_features,
            levels,
            known_sources,
            known_excerpts,
            calculations_from_rows(rows),
        )

    async def _record_market_data(self, job: Job, checkpoint: ResearchCheckpoint) -> None:
        """Market-data cost is its own ledger and does not draw down the AI/search ceiling."""
        if checkpoint.run_id is None:
            return
        budget = self._budget(checkpoint, job)
        reservation = await budget.reserve(
            category="market_data",
            provider=self._deps.adapter.capabilities.provider,
            estimate=Decimal(0),
            unit_type="records",
        )
        await budget.reconcile(reservation, Decimal(0))

    def _budget(self, checkpoint: ResearchCheckpoint, job: Job) -> BudgetService:
        return BudgetService(
            self._deps.engine,
            self._deps.limits,
            run_id=_required_uuid(checkpoint.run_id, "run"),
            job_id=job.id,
        )

    async def _ensure_run(self, job: Job, checkpoint: ResearchCheckpoint) -> ResearchCheckpoint:
        if checkpoint.run_id is not None:
            return checkpoint
        provenance = "recorded" if self._deps.provider.name == "recorded" else "fixture"
        async with self._deps.engine.begin() as conn:
            run_id = await jobs.earliest_run_id(conn, job.id)
            if run_id is None:
                run = await jobs.insert_run(
                    conn,
                    job_id=job.id,
                    conversation_id=job.conversation_id,
                    provider=self._deps.provider.name,
                    provenance=provenance,
                    model=self._deps.model,
                    prompt_version=PROMPT_VERSION,
                )
                run_id = run.id
            updated = checkpoint.model_copy(update={"run_id": run_id})
            saved = await jobs.save_checkpoint(
                conn,
                job_id=job.id,
                worker_id=self._deps.worker_id,
                checkpoint=dump_checkpoint(updated),
                lease_seconds=self._deps.lease_seconds,
            )
            _raise_if_lease_lost(saved, job.id)
        return updated

    async def _save(self, job: Job, checkpoint: ResearchCheckpoint) -> None:
        async with self._deps.engine.begin() as conn:
            saved = await jobs.save_checkpoint(
                conn,
                job_id=job.id,
                worker_id=self._deps.worker_id,
                checkpoint=dump_checkpoint(checkpoint),
                lease_seconds=self._deps.lease_seconds,
            )
            _raise_if_lease_lost(saved, job.id)
            if checkpoint.run_id is not None:
                await jobs.update_run(
                    conn,
                    run_id=checkpoint.run_id,
                    status="running",
                    current_stage=_last_stage(checkpoint),
                    stages_completed=list(checkpoint.stages_completed),
                    usage=_usage(checkpoint),
                )

    async def _note(
        self, job: Job, checkpoint: ResearchCheckpoint, stage: str, message: str
    ) -> ResearchCheckpoint:
        if checkpoint.run_id is None:
            return checkpoint
        updated = checkpoint.model_copy(update={"event_sequence": checkpoint.event_sequence + 1})
        async with self._deps.engine.begin() as conn:
            await jobs.append_run_event(
                conn,
                run_id=checkpoint.run_id,
                sequence=checkpoint.event_sequence,
                stage=stage,
                level="info",
                message=redact(message, self._deps.secrets),
                data={},
            )
            saved = await jobs.save_checkpoint(
                conn,
                job_id=job.id,
                worker_id=self._deps.worker_id,
                checkpoint=dump_checkpoint(updated),
                lease_seconds=self._deps.lease_seconds,
            )
            _raise_if_lease_lost(saved, job.id)
        if self._deps.progress is not None:
            await self._deps.progress(
                ProgressEvent(
                    event="progress",
                    message=message,
                    stage=stage,
                    run_id=checkpoint.run_id,
                    job_id=job.id,
                )
            )
        return updated

    async def _pause(self, job: Job, checkpoint: ResearchCheckpoint, reason: str) -> NoReturn:
        scheduled = datetime.now(UTC) + timedelta(seconds=30)
        async with self._deps.engine.begin() as conn:
            updated = await jobs.set_state(
                conn,
                job_id=job.id,
                worker_id=self._deps.worker_id,
                state="partial",
                checkpoint=dump_checkpoint(checkpoint),
                last_error=reason,
                scheduled_for=scheduled,
            )
            if updated is None:
                raise LeaseLostError(str(job.id))
            if checkpoint.run_id is not None:
                await jobs.update_run(
                    conn,
                    run_id=checkpoint.run_id,
                    status="partial",
                    current_stage=_last_stage(checkpoint),
                    stages_completed=list(checkpoint.stages_completed),
                    usage=_usage(checkpoint),
                    error=reason,
                )
        raise WorkflowPausedError(reason)

    async def _finish(self, job: Job, checkpoint: ResearchCheckpoint) -> None:
        run_status: JobState = "partial" if checkpoint.partial_research else "completed"
        async with self._deps.engine.begin() as conn:
            updated = await jobs.set_state(
                conn,
                job_id=job.id,
                worker_id=self._deps.worker_id,
                state="completed",
                checkpoint=dump_checkpoint(checkpoint),
                last_error=checkpoint.stop_reason,
            )
            if updated is None:
                raise LeaseLostError(str(job.id))
            if checkpoint.run_id is not None:
                await jobs.update_run(
                    conn,
                    run_id=checkpoint.run_id,
                    status=run_status,
                    current_stage="notify",
                    stages_completed=list(checkpoint.stages_completed),
                    usage=_usage(checkpoint),
                    finished=True,
                    error=checkpoint.stop_reason,
                )
        if self._deps.progress is not None and checkpoint.run_id is not None:
            await self._deps.progress(
                ProgressEvent(
                    event="done",
                    message=run_status,
                    stage="notify",
                    run_id=checkpoint.run_id,
                    job_id=job.id,
                    job_state="completed",
                    is_demonstration=True if self._deps.provider.name == "recorded" else None,
                    artifact_id=checkpoint.artifact_id,
                )
            )

    def _expired(self) -> bool:
        return time.monotonic() >= self._deadline


def _mark_partial(checkpoint: ResearchCheckpoint, reason: str) -> ResearchCheckpoint:
    return checkpoint.model_copy(
        update={
            "partial_research": True,
            "stop_reason": checkpoint.stop_reason or reason,
        }
    )


def _with_stage(checkpoint: ResearchCheckpoint, stage: str) -> ResearchCheckpoint:
    if stage in checkpoint.stages_completed:
        return checkpoint
    completed = [*checkpoint.stages_completed, cast("RunStage", stage)]
    return checkpoint.model_copy(update={"stages_completed": completed})


def _last_stage(checkpoint: ResearchCheckpoint) -> str | None:
    if not checkpoint.stages_completed:
        return None
    return checkpoint.stages_completed[-1]


def _usage(checkpoint: ResearchCheckpoint) -> Usage:
    return Usage(retrieval_calls=checkpoint.retrievals_used)


def _required_uuid(value: UUID | None, label: str) -> UUID:
    if value is None:
        msg = f"missing {label}"
        raise RuntimeError(msg)
    return value


def _unique_ids(values: list[UUID]) -> list[UUID]:
    return list(dict.fromkeys(values))


def _summary(feature: TAFeature) -> dict[str, JsonValue]:
    return {
        "id": str(feature.id),
        "annotation_id": annotation_id_for(feature.id),
        "detector": feature.detector,
        "calc_version": feature.calc_version,
        "direction": feature.direction,
        "state": feature.state,
        "levels": [
            {"name": level.name, "price": format(level.price, "f"), "role": level.role}
            for level in feature.levels
        ],
    }


async def _persist_output(
    conn: AsyncConnection,
    *,
    features: list[TAFeature],
    events: list[TAEvent],
    transitions: list[TAFeatureTransition],
    instrument_id: UUID,
    snapshot_id: UUID,
    contract_code: str | None,
    data_revision: str | None,
) -> tuple[list[UUID], list[dict[str, JsonValue]]]:
    feature_ids: list[UUID] = []
    summaries: list[dict[str, JsonValue]] = []
    for feature in features:
        stored = stamp_feature(
            feature.model_copy(
                update={
                    "instrument_id": instrument_id,
                    "snapshot_id": snapshot_id,
                    "contract_code": contract_code,
                    "data_revision": data_revision or feature.data_revision,
                }
            )
        )
        await market.insert_feature(conn, stored)
        feature_ids.append(stored.id)
        summaries.append(_summary(stored))
    for event in events:
        await market.insert_event(
            conn,
            event.model_copy(
                update={"instrument_id": instrument_id, "contract_code": contract_code}
            ),
        )
    for transition in transitions:
        await market.insert_transition(conn, transition)
    return feature_ids, summaries


def _lookup(registry: DetectorRegistry, name: str) -> Detector | None:
    """Only calc 1.0.0. A later registered version must not replace this slice."""
    try:
        return registry.get(cast("DetectorName", name), CALC_VERSION)
    except KeyError:
        return None


def _raise_if_lease_lost(saved: bool, job_id: UUID) -> None:
    """Call before the writing transaction closes.

    ``save_checkpoint`` returns false when this worker no longer owns the row. Raising after
    the context manager commits the insert and leaves a run, revision, or alert the checkpoint
    does not know about.
    """
    if not saved:
        raise LeaseLostError(str(job_id))


def _asset(value: str | None) -> AssetClass:
    if value in _ASSET_CLASSES:
        return cast("AssetClass", value)
    return "futures"


def _provenance(value: str) -> Provenance:
    if value == "live":
        return "live"
    if value == "fixture":
        return "fixture"
    return "recorded"


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value)


def _as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _thesis(checkpoint: ResearchCheckpoint) -> Thesis:
    if checkpoint.thesis is None:
        msg = "thesis is missing from the checkpoint"
        raise RuntimeError(msg)
    return Thesis.model_validate(checkpoint.thesis)
