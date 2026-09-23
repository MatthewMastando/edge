"""Adapter that serves generated fixture data. Everything it returns is provenance=fixture."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

from trading_core.data.adapter import (
    AdapterCapabilities,
    BarsRequest,
    InstrumentResolution,
    TradesRequest,
    UnknownSymbolError,
)
from trading_core.domain.market import BarSeries, TradeBatch
from trading_core.fixtures.generator import bars_key, trades_key
from trading_core.fixtures.manifest import FixtureManifest, read_manifest
from trading_core.labeling import FeedLabel
from trading_core.storage.local import LocalParquetStore
from trading_core.storage.schemas import TIMESTAMP_TYPE, table_to_bars, table_to_trades

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from trading_core.domain.instruments import FuturesContract, Instrument


class FixtureAdapter:
    def __init__(self, root: Path, manifest: FixtureManifest | None = None) -> None:
        self._root = root
        self._store = LocalParquetStore(root)
        self._manifest = manifest or read_manifest(root)
        self._instruments = {i.symbol: i for i in self._manifest.instruments}
        self._contracts = {c.contract_code: c for c in self._manifest.futures_contracts}
        self._calendars = {c.id: c for c in self._manifest.session_calendars}

    @property
    def manifest(self) -> FixtureManifest:
        return self._manifest

    @property
    def root(self) -> Path:
        return self._root

    def feed_label(self, symbol: str) -> FeedLabel:
        del symbol
        note = self.capabilities.coverage_note or "synthetic demonstration data"
        return FeedLabel(
            source="fixture",
            coverage=note,
            delay="none; demonstration data has no exchange delay",
            provenance="fixture",
        )

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            provider="fixture",
            provenance="fixture",
            has_trades=True,
            consolidated_equities=False,
            coverage_note="Synthetic demonstration data generated from a seed; not market data.",
        )

    async def list_instruments(self) -> list[Instrument]:
        return list(self._manifest.instruments)

    async def list_futures_contracts(self, root: str | None = None) -> list[FuturesContract]:
        return [c for c in self._manifest.futures_contracts if root is None or c.root == root]

    async def resolve(self, symbol: str) -> InstrumentResolution:
        contract = self._contracts.get(symbol)
        instrument = (
            self._instruments.get(contract.root) if contract else self._instruments.get(symbol)
        )
        if instrument is None:
            msg = f"unknown fixture symbol {symbol!r}"
            raise UnknownSymbolError(msg)
        if contract is None and instrument.asset_class == "futures":
            msg = f"{symbol!r} is a futures root; request a listed contract such as {symbol}Z6"
            raise UnknownSymbolError(msg)
        return InstrumentResolution(
            instrument=instrument,
            contract=contract,
            calendar=self._calendars[instrument.session_calendar_id],
        )

    async def get_bars(self, request: BarsRequest) -> BarSeries:
        resolution = await self.resolve(request.symbol)
        if request.timeframe != self._manifest.timeframe:
            msg = f"fixture data only has {self._manifest.timeframe} bars"
            raise UnknownSymbolError(msg)
        table = self._store.get_table(bars_key(request.symbol, request.timeframe))
        table = _slice(table, "origin_time", request.start, request.end, request.limit)
        return BarSeries(
            instrument_id=resolution.instrument.id,
            contract_code=resolution.contract.contract_code if resolution.contract else None,
            timeframe=request.timeframe,
            data_revision=self._manifest.data_revision,
            provenance="fixture",
            bars=table_to_bars(table),
        )

    async def get_trades(self, request: TradesRequest) -> TradeBatch:
        resolution = await self.resolve(request.symbol)
        table = self._store.get_table(trades_key(request.symbol))
        table = _slice(table, "trade_time", request.start, request.end, request.limit)
        return TradeBatch(
            instrument_id=resolution.instrument.id,
            contract_code=resolution.contract.contract_code if resolution.contract else None,
            data_revision=self._manifest.data_revision,
            provenance="fixture",
            trades=table_to_trades(table),
        )


def _slice(
    table: pa.Table,
    column: str,
    start: datetime | None,
    end: datetime | None,
    limit: int | None,
) -> pa.Table:
    if start is not None:
        table = table.filter(pc.greater_equal(table[column], pa.scalar(start, TIMESTAMP_TYPE)))
    if end is not None:
        table = table.filter(pc.less(table[column], pa.scalar(end, TIMESTAMP_TYPE)))
    if limit is not None and table.num_rows > limit:
        table = table.slice(table.num_rows - limit, limit)
    return table
