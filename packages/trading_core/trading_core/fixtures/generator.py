"""Deterministic, seeded generator of contract-shaped bars and trade prints.

Design:

- Trades are generated first as a tick-aligned random walk; bars are aggregated from them, so
  OHLCV and volume-at-price are always mutually consistent.
- All prices are integers of ticks multiplied by the exact ``tick_size`` Decimal.
- Randomness comes from ``numpy.random.default_rng([seed, crc32(symbol)])`` so instruments are
  independent yet fully reproducible.
- ``data_revision`` is derived from the generator version, the seed and a hash of the YAML inputs.
"""

from __future__ import annotations

import zlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

import numpy as np

from trading_core.domain.common import TIMEFRAME_SECONDS, FixtureLabel, Timeframe
from trading_core.domain.market import Bar, MarketSnapshot, Trade, TradeSide
from trading_core.fixtures.manifest import FixtureManifest, read_manifest, write_manifest
from trading_core.fixtures.sessions import bar_origins
from trading_core.fixtures.spec import (
    DEFAULT_FIXTURES_DIR,
    FixtureInputs,
    InstrumentSpec,
    fixture_uuid,
    load_fixture_inputs,
)
from trading_core.storage.local import LocalParquetStore
from trading_core.storage.schemas import bars_to_table, content_hash, trades_to_table

if TYPE_CHECKING:
    from pathlib import Path
    from uuid import UUID

    from trading_core.domain.instruments import SessionCalendar
    from trading_core.storage.base import StoredObject

GENERATOR_NAME = "trading_core.fixtures.generator"
GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20260923
DEFAULT_START_DATE = date(2026, 8, 31)
DEFAULT_SESSION_DAYS = 10
DEFAULT_TIMEFRAME: Timeframe = "5m"


def data_revision_for(seed: int, inputs_hash: str, start: date, days: int, timeframe: str) -> str:
    stamp = zlib.crc32(f"{inputs_hash}|{start.isoformat()}|{days}|{timeframe}".encode())
    return f"fixture-{GENERATOR_VERSION}-s{seed}-{stamp:08x}"


def bars_key(symbol: str, timeframe: str) -> str:
    return f"bars/{symbol}/{timeframe}.parquet"


def trades_key(symbol: str) -> str:
    return f"trades/{symbol}.parquet"


class GeneratedSeries:
    """In-memory result for one symbol before it is written."""

    def __init__(
        self,
        *,
        symbol: str,
        contract_code: str | None,
        bars: list[Bar],
        trades: list[Trade],
        coverage_note: str | None,
    ) -> None:
        self.symbol = symbol
        self.contract_code = contract_code
        self.bars = bars
        self.trades = trades
        self.coverage_note = coverage_note


def _quantize_size(value: float, decimals: int) -> Decimal:
    if decimals == 0:
        return Decimal(round(value))
    return Decimal(f"{value:.{decimals}f}")


def generate_series(
    spec: InstrumentSpec,
    calendar: SessionCalendar,
    *,
    contract_code: str | None,
    seed: int,
    start: date,
    session_days: int,
    timeframe: Timeframe,
    data_revision: str,
) -> GeneratedSeries:
    bar_seconds = TIMEFRAME_SECONDS[timeframe]
    origins = bar_origins(calendar, start, session_days, bar_seconds)
    if not origins:
        msg = f"{spec.symbol}: calendar {calendar.id} produced no bars"
        raise ValueError(msg)

    rng = np.random.default_rng([seed, zlib.crc32(spec.symbol.encode())])
    params = spec.fixture
    tick = spec.tick_size
    start_ticks = int((params.start_price / tick).to_integral_value())

    counts = np.maximum(rng.poisson(params.trades_per_bar, size=len(origins)), 1)
    total = int(counts.sum())
    steps = np.rint(rng.normal(0.0, params.step_ticks_sd, size=total)).astype(np.int64)
    ticks = start_ticks + np.cumsum(steps)
    ticks = np.maximum(ticks, 1)
    raw_sizes: np.ndarray[tuple[int], np.dtype[np.float64]]
    if params.size_decimals == 0:
        raw_sizes = rng.integers(int(params.size_min), int(params.size_max) + 1, size=total).astype(
            np.float64
        )
    else:
        raw_sizes = rng.uniform(params.size_min, params.size_max, size=total)
    offsets = rng.uniform(0.0, bar_seconds, size=total)
    sides = rng.integers(0, 2, size=total) if spec.asset_class == "crypto_spot" else None

    instrument_id = fixture_uuid("instrument", spec.symbol)
    trades: list[Trade] = []
    bars: list[Bar] = []
    cursor = 0
    sequence = 0
    for bar_index, (_session_date, origin) in enumerate(origins):
        n = int(counts[bar_index])
        window = slice(cursor, cursor + n)
        cursor += n
        bar_ticks = ticks[window]
        bar_sizes = raw_sizes[window]
        bar_offsets = np.sort(offsets[window])
        bar_sides = sides[window] if sides is not None else None

        volume = Decimal(0)
        notional = Decimal(0)
        for j in range(n):
            price = Decimal(int(bar_ticks[j])) * tick
            size = _quantize_size(float(bar_sizes[j]), params.size_decimals)
            side: TradeSide = "unknown"
            if bar_sides is not None:
                side = "buy" if int(bar_sides[j]) == 1 else "sell"
            trades.append(
                Trade(
                    instrument_id=instrument_id,
                    contract_code=contract_code,
                    sequence=sequence,
                    trade_time=origin + timedelta(microseconds=int(bar_offsets[j] * 1_000_000)),
                    trade_tz=calendar.timezone,
                    price=price,
                    size=size,
                    side=side,
                    venue=spec.venue,
                    data_revision=data_revision,
                    provenance="fixture",
                )
            )
            sequence += 1
            volume += size
            notional += price * size

        bars.append(
            Bar(
                instrument_id=instrument_id,
                contract_code=contract_code,
                timeframe=timeframe,
                origin_time=origin,
                origin_tz=calendar.timezone,
                open=Decimal(int(bar_ticks[0])) * tick,
                high=Decimal(int(bar_ticks.max())) * tick,
                low=Decimal(int(bar_ticks.min())) * tick,
                close=Decimal(int(bar_ticks[-1])) * tick,
                volume=volume,
                trade_count=n,
                vwap=(notional / volume).quantize(Decimal("0.00000001")),
                is_complete=True,
                data_revision=data_revision,
                provenance="fixture",
            )
        )

    return GeneratedSeries(
        symbol=contract_code or spec.symbol,
        contract_code=contract_code,
        bars=bars,
        trades=trades,
        coverage_note=params.coverage_note,
    )


def _snapshot(
    *,
    series: GeneratedSeries,
    instrument_id: UUID,
    kind: Literal["bars", "trades"],
    timeframe: Timeframe | None,
    stored: StoredObject,
    data_revision: str,
    range_start: datetime,
    range_end: datetime,
) -> MarketSnapshot:
    return MarketSnapshot(
        id=fixture_uuid("snapshot", f"{data_revision}:{stored.key}"),
        instrument_id=instrument_id,
        contract_code=series.contract_code,
        timeframe=timeframe,
        kind=kind,
        range_start=range_start,
        range_end=range_end,
        as_of=range_end,
        provider="fixture",
        provenance="fixture",
        data_revision=data_revision,
        storage_key=stored.key,
        row_count=stored.row_count,
        content_hash=stored.content_hash,
        coverage_note=series.coverage_note,
    )


def generate_fixtures(
    *,
    output_dir: Path,
    fixtures_dir: Path = DEFAULT_FIXTURES_DIR,
    seed: int = DEFAULT_SEED,
    start: date = DEFAULT_START_DATE,
    session_days: int = DEFAULT_SESSION_DAYS,
    timeframe: Timeframe = DEFAULT_TIMEFRAME,
    inputs: FixtureInputs | None = None,
) -> FixtureManifest:
    """Generate every series, write Parquet through the local store and return the manifest."""
    inputs = inputs or load_fixture_inputs(fixtures_dir)
    data_revision = data_revision_for(seed, inputs.inputs_hash, start, session_days, timeframe)
    store = LocalParquetStore(output_dir)
    bar_seconds = TIMEFRAME_SECONDS[timeframe]

    snapshots: list[MarketSnapshot] = []
    last_close: datetime | None = None
    common_metadata = {
        "provenance": "fixture",
        "generator": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "seed": str(seed),
        "data_revision": data_revision,
    }

    for spec in inputs.definitions.instruments:
        calendar = inputs.calendar_for(spec.session_calendar_id)
        contracts = inputs.definitions.contracts_for(spec.symbol)
        targets: list[str | None] = [c.contract_code for c in contracts] or [None]
        for contract_code in targets:
            series = generate_series(
                spec,
                calendar,
                contract_code=contract_code,
                seed=seed,
                start=start,
                session_days=session_days,
                timeframe=timeframe,
                data_revision=data_revision,
            )
            range_start = series.bars[0].origin_time
            range_end = series.bars[-1].origin_time + timedelta(seconds=bar_seconds)
            last_close = range_end if last_close is None else max(last_close, range_end)
            metadata = {**common_metadata, "symbol": series.symbol, "instrument": spec.symbol}

            stored_bars = store.put_table(
                bars_key(series.symbol, timeframe),
                bars_to_table(series.bars),
                {**metadata, "kind": "bars", "timeframe": timeframe},
            )
            stored_trades = store.put_table(
                trades_key(series.symbol),
                trades_to_table(series.trades),
                {**metadata, "kind": "trades"},
            )
            instrument_id = fixture_uuid("instrument", spec.symbol)
            snapshots.append(
                _snapshot(
                    series=series,
                    instrument_id=instrument_id,
                    kind="bars",
                    timeframe=timeframe,
                    stored=stored_bars,
                    data_revision=data_revision,
                    range_start=range_start,
                    range_end=range_end,
                )
            )
            snapshots.append(
                _snapshot(
                    series=series,
                    instrument_id=instrument_id,
                    kind="trades",
                    timeframe=None,
                    stored=stored_trades,
                    data_revision=data_revision,
                    range_start=range_start,
                    range_end=range_end,
                )
            )

    assert last_close is not None
    manifest = FixtureManifest(
        label=FixtureLabel(
            generator=GENERATOR_NAME,
            generator_version=GENERATOR_VERSION,
            seed=seed,
            data_revision=data_revision,
            generated_at=datetime.now(tz=UTC),
        ),
        data_revision=data_revision,
        seed=seed,
        start_date=start,
        session_days=session_days,
        timeframe=timeframe,
        as_of=last_close,
        inputs_hash=inputs.inputs_hash,
        instruments=[spec.to_instrument() for spec in inputs.definitions.instruments],
        futures_contracts=[c.to_contract() for c in inputs.definitions.futures_contracts],
        roll_maps=[r.to_entry() for r in inputs.definitions.roll_maps],
        session_calendars=sorted(inputs.calendars.values(), key=lambda c: c.id),
        snapshots=snapshots,
    )
    write_manifest(output_dir, manifest)
    return manifest


def verify_fixtures(output_dir: Path) -> list[str]:
    """Re-hash every Parquet file and return a list of mismatches (empty when all good)."""
    manifest = read_manifest(output_dir)
    store = LocalParquetStore(output_dir)
    problems: list[str] = []
    for snapshot in manifest.snapshots:
        if not store.exists(snapshot.storage_key):
            problems.append(f"missing {snapshot.storage_key}")
            continue
        table = store.get_table(snapshot.storage_key)
        actual = content_hash(table)
        if actual != snapshot.content_hash:
            problems.append(f"hash mismatch {snapshot.storage_key}")
        if table.num_rows != snapshot.row_count:
            problems.append(f"row count mismatch {snapshot.storage_key}")
        metadata = store.get_metadata(snapshot.storage_key)
        if metadata.get("provenance") != "fixture":
            problems.append(f"unlabeled provenance {snapshot.storage_key}")
    return problems
