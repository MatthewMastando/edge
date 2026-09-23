"""Record confirmed TA events without creating a research artifact.

A scan is cheap relative to a thesis. Trigger rules decide later whether any of those
events become a research job.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from trading_core.data.adapter import (
    BarsRequest,
    InstrumentResolution,
    TradesRequest,
    UnknownSymbolError,
)
from trading_core.domain.market import BarSeries, MarketSnapshot, TradeBatch
from trading_core.harness.annotations import stamp_feature
from trading_core.harness.budget import BudgetService
from trading_core.storage.repositories import jobs, market, reference
from trading_core.storage.schemas import bars_to_table, trades_to_table
from trading_core.ta import CALC_VERSION, DetectorInput, DetectorRegistry, InsufficientDataError

if TYPE_CHECKING:
    from pydantic import JsonValue
    from sqlalchemy.ext.asyncio import AsyncConnection

    from trading_core.domain.common import Timeframe
    from trading_core.domain.jobs import Job, JobState
    from trading_core.domain.ta import DetectorName, TAFeature
    from trading_core.harness.deps import WorkflowDeps

log = logging.getLogger("trading_core.automation.scan")

_DETECTORS = (
    "volume_profile",
    "fvg",
    "liquidity_sweep",
    "bos",
    "order_block",
    "rsi_divergence",
)
_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1d"}


async def run_scan(deps: WorkflowDeps, job: Job) -> None:
    symbols = _symbols(job.payload.get("symbols"))
    done = _symbols(job.checkpoint.get("completed_symbols"))
    timeframe = _timeframe(job.payload.get("timeframe"))
    try:
        for symbol in symbols:
            if symbol in done:
                continue
            await _scan_symbol(deps, job, symbol, timeframe)
            done.append(symbol)
            await _checkpoint(deps, job, done)
    except Exception as exc:
        log.error("ta scan %s failed: %s", job.id, exc)
        await _finish(deps, job, done, "partial", str(exc))
        return
    await _finish(deps, job, done, "completed", None)


async def _scan_symbol(deps: WorkflowDeps, job: Job, symbol: str, timeframe: Timeframe) -> None:
    resolved = await deps.adapter.resolve(symbol)
    async with deps.engine.begin() as conn:
        await reference.upsert_session_calendar(conn, resolved.calendar)
        instrument = await reference.upsert_instrument(conn, resolved.instrument)
        contract_code = None
        if resolved.contract is not None:
            stored = await reference.upsert_futures_contract(
                conn, resolved.contract.model_copy(update={"instrument_id": instrument.id})
            )
            contract_code = stored.contract_code
    bars = await deps.adapter.get_bars(BarsRequest(symbol=symbol, timeframe=timeframe, limit=5000))
    trades: TradeBatch | None
    try:
        trades = await deps.adapter.get_trades(TradesRequest(symbol=symbol, limit=200_000))
    except UnknownSymbolError:
        trades = None
    if not bars.bars:
        return
    last = bars.bars[-1]
    first = bars.bars[0]
    bar_key = f"scans/{instrument.id}/{bars.data_revision}/{symbol}-{timeframe}-bars.parquet"
    stored_bars = deps.store.put_table(bar_key, bars_to_table(bars.bars))
    snapshot = MarketSnapshot(
        id=uuid4(),
        instrument_id=instrument.id,
        contract_code=contract_code,
        timeframe=timeframe,
        kind="bars",
        range_start=first.origin_time,
        range_end=last.origin_time,
        as_of=last.origin_time,
        as_of_tz=last.origin_tz,
        provider=deps.adapter.capabilities.provider,
        provenance=bars.provenance,
        data_revision=bars.data_revision,
        storage_key=bar_key,
        row_count=stored_bars.row_count,
        content_hash=stored_bars.content_hash,
        coverage_note=deps.adapter.capabilities.coverage_note,
    )
    async with deps.engine.begin() as conn:
        snapshot_id = await market.insert_snapshot(conn, snapshot, backend=deps.store.backend)
        if trades is not None and trades.trades:
            await _store_trades(deps, instrument.id, trades, snapshot)
        await _run_detectors(
            conn,
            deps.detectors,
            resolved=resolved,
            instrument_id=instrument.id,
            contract_code=contract_code,
            snapshot_id=snapshot_id,
            bars=bars,
            trades=trades,
        )
    budget = BudgetService(deps.engine, deps.limits, run_id=None, job_id=job.id)
    reservation = await budget.reserve(
        category="market_data",
        provider=deps.adapter.capabilities.provider,
        estimate=Decimal(0),
        unit_type="records",
        units=Decimal(stored_bars.row_count),
    )
    await budget.reconcile(reservation, Decimal(0))


async def _store_trades(
    deps: WorkflowDeps, instrument_id: UUID, trades: TradeBatch, snapshot: MarketSnapshot
) -> None:
    label = snapshot.contract_code or "spot"
    trade_key = f"scans/{instrument_id}/{trades.data_revision}/{label}-trades.parquet"
    stored = deps.store.put_table(trade_key, trades_to_table(trades.trades))
    trade_snapshot = snapshot.model_copy(
        update={
            "id": uuid4(),
            "timeframe": None,
            "kind": "trades",
            "storage_key": trade_key,
            "row_count": stored.row_count,
            "content_hash": stored.content_hash,
            "range_start": trades.trades[0].trade_time,
            "range_end": trades.trades[-1].trade_time,
            "provenance": trades.provenance,
            "data_revision": trades.data_revision,
        }
    )
    async with deps.engine.begin() as conn:
        await market.insert_snapshot(conn, trade_snapshot, backend=deps.store.backend)


async def _run_detectors(
    conn: AsyncConnection,
    detectors: DetectorRegistry,
    *,
    resolved: InstrumentResolution,
    instrument_id: UUID,
    contract_code: str | None,
    snapshot_id: UUID,
    bars: BarSeries,
    trades: TradeBatch | None,
) -> None:
    detector_input = DetectorInput(
        instrument=resolved.instrument.model_copy(update={"id": instrument_id}),
        contract=(
            None
            if resolved.contract is None
            else resolved.contract.model_copy(update={"instrument_id": instrument_id})
        ),
        calendar=resolved.calendar,
        session="current_session",
        bars=bars.model_copy(
            update={
                "instrument_id": instrument_id,
                "bars": [
                    bar.model_copy(update={"instrument_id": instrument_id}) for bar in bars.bars
                ],
            }
        ),
        trades=(
            None
            if trades is None
            else trades.model_copy(
                update={
                    "instrument_id": instrument_id,
                    "trades": [
                        trade.model_copy(update={"instrument_id": instrument_id})
                        for trade in trades.trades
                    ],
                }
            )
        ),
        snapshot_id=snapshot_id,
    )
    for name in _DETECTORS:
        try:
            detector = detectors.get(cast("DetectorName", name), CALC_VERSION)
        except KeyError:
            continue
        try:
            output = detector.run(
                detector_input.model_copy(update={"parameters": detector.default_parameters()})
            )
        except InsufficientDataError:
            continue
        for feature in output.features:
            stamped = _stamp(feature, instrument_id, snapshot_id, contract_code, bars.data_revision)
            await market.insert_feature(conn, stamped)
        for event in output.events:
            await market.insert_event(
                conn,
                event.model_copy(
                    update={"instrument_id": instrument_id, "contract_code": contract_code}
                ),
            )


def _stamp(
    feature: TAFeature,
    instrument_id: UUID,
    snapshot_id: UUID,
    contract_code: str | None,
    data_revision: str,
) -> TAFeature:
    return stamp_feature(
        feature.model_copy(
            update={
                "instrument_id": instrument_id,
                "snapshot_id": snapshot_id,
                "contract_code": contract_code,
                "data_revision": data_revision,
            }
        )
    )


async def _checkpoint(deps: WorkflowDeps, job: Job, done: list[str]) -> None:
    async with deps.engine.begin() as conn:
        await jobs.save_checkpoint(
            conn,
            job_id=job.id,
            worker_id=deps.worker_id,
            checkpoint=cast("dict[str, JsonValue]", {"completed_symbols": done}),
            lease_seconds=deps.lease_seconds,
        )


async def _finish(
    deps: WorkflowDeps, job: Job, done: list[str], state: JobState, error: str | None
) -> None:
    async with deps.engine.begin() as conn:
        await jobs.set_state(
            conn,
            job_id=job.id,
            worker_id=deps.worker_id,
            state=state,
            checkpoint=cast("dict[str, JsonValue]", {"completed_symbols": done}),
            last_error=error,
        )


def _symbols(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _timeframe(value: object) -> Timeframe:
    if isinstance(value, str) and value in _TIMEFRAMES:
        return cast("Timeframe", value)
    return "5m"
