"""Databento historical client for listed futures. Unavailable without an API key.

Volume is copied from the vendor field only. A missing print is not stored as zero.
"""

from __future__ import annotations

import base64
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from trading_core.data.adapter import (
    AdapterCapabilities,
    BarsRequest,
    InstrumentResolution,
    TradesRequest,
    UnknownSymbolError,
)
from trading_core.data.parse import (
    csv_rows,
    fixed_price,
    futures_contract_parts,
    is_continuous_symbol,
    ns_to_datetime,
    parse_decimal,
    revision_id,
)
from trading_core.domain.instruments import FuturesContract, Instrument, SettlementType
from trading_core.domain.market import Bar, BarSeries, Trade, TradeBatch, TradeSide
from trading_core.http_client import HttpRequest, Transport, query_url
from trading_core.labeling import FeedLabel, SourceFailure, missing_credential

if TYPE_CHECKING:
    from decimal import Decimal

    from trading_core.data.reference import ReferenceBook
    from trading_core.domain.common import Provenance, Timeframe
    from trading_core.fixtures.spec import InstrumentSpec

_DATASET = "GLBX.MDP3"
_BASE = "https://hist.databento.com/v0/timeseries.get_range"
_SCHEMA_TIMEFRAME = {"1m": "ohlcv-1m", "1h": "ohlcv-1h", "1d": "ohlcv-1d"}
_LIVE_NAMESPACE = UUID("b7e1c4a2-9d30-4f6e-8a11-2c5d0e7f91ab")
_COVERAGE = (
    "GLBX.MDP3 historical definitions, OHLCV, and trades. "
    "Tick size, settlement, and the session calendar come from the versioned root map "
    "when the definition row omits them. First notice is null unless that map lists the contract. "
    "Volume is never filled in."
)


def _id(key: str) -> UUID:
    return uuid5(_LIVE_NAMESPACE, f"databento:{key}")


class DatabentoAdapter:
    def __init__(
        self,
        *,
        api_key: str,
        reference: ReferenceBook,
        transport: Transport,
        provenance: Provenance = "live",
        replay_note: str | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._reference = reference
        self._transport = transport
        self._provenance: Provenance = provenance
        self._replay_note = replay_note

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            provider="databento",
            provenance=self._provenance,
            has_trades=bool(self._api_key),
            consolidated_equities=None,
            coverage_note=self.feed_label("*").as_note(),
        )

    def feed_label(self, symbol: str) -> FeedLabel:
        coverage = _COVERAGE if symbol == "*" else f"{_COVERAGE} Symbol {symbol}."
        if self._replay_note:
            coverage = f"{coverage} {self._replay_note}"
        if not self._api_key:
            coverage = f"{coverage} DATABENTO_API_KEY is not set; no request is sent."
        return FeedLabel(
            source="databento",
            coverage=coverage,
            delay="historical; not a realtime feed",
            provenance=self._provenance,
        )

    async def list_instruments(self) -> list[Instrument]:
        self._require_key()
        return [
            self._instrument(spec)
            for spec in self._reference.instruments.values()
            if spec.asset_class == "futures"
        ]

    async def list_futures_contracts(self, root: str | None = None) -> list[FuturesContract]:
        self._require_key()
        if root is None:
            raise SourceFailure(
                source="databento",
                coverage="a futures root is required",
                delay="historical; not a realtime feed",
                reason="the full outright list is not requested without a root",
                status="missing_coverage",
            )
        rows = await self._rows(
            symbols=f"{root}.FUT",
            schema="definition",
            stype_in="parent",
            start=_iso(_days_ago(2)),
            end=_iso(datetime.now(UTC)),
        )
        contracts = [self._contract(row) for row in rows if row.get("raw_symbol")]
        if not contracts:
            raise SourceFailure(
                source="databento",
                coverage=f"no definition rows for {root}.FUT",
                delay="historical; not a realtime feed",
                reason="Databento returned no contract definitions",
                status="missing_coverage",
            )
        return contracts

    async def resolve(self, symbol: str) -> InstrumentResolution:
        self._require_key()
        self._reject_continuous(symbol)
        parts = futures_contract_parts(symbol)
        if parts is None:
            self._reject_root(symbol)
            raise UnknownSymbolError(f"unknown futures symbol {symbol!r}")
        root, code = parts
        rows = await self._rows(
            symbols=code,
            schema="definition",
            stype_in="raw_symbol",
            start=_iso(_days_ago(2)),
            end=_iso(datetime.now(UTC)),
        )
        match = next((row for row in rows if row.get("raw_symbol") == code), None)
        chosen = match if match is not None else (rows[0] if rows else None)
        if chosen is None:
            raise SourceFailure(
                source="databento",
                coverage=f"no definition row for {code}",
                delay="historical; not a realtime feed",
                reason="contract definition was not returned and was not invented",
                status="missing_coverage",
            )
        if not chosen.get("raw_symbol"):
            chosen = {**chosen, "raw_symbol": code}
        contract = self._contract(chosen)
        instrument = self._instrument(self._require_root(root))
        calendar = self._reference.calendar(instrument.session_calendar_id)
        return InstrumentResolution(instrument=instrument, contract=contract, calendar=calendar)

    async def get_bars(self, request: BarsRequest) -> BarSeries:
        schema = _SCHEMA_TIMEFRAME.get(request.timeframe)
        if schema is None:
            raise SourceFailure(
                source="databento",
                coverage=f"no ohlcv schema for {request.timeframe}",
                delay="historical; not a realtime feed",
                reason=f"{request.timeframe} was not aggregated from another schema",
                status="missing_coverage",
            )
        resolution = await self.resolve(request.symbol)
        end = request.end or datetime.now(UTC)
        start = request.start or (end - timedelta(days=5))
        body, rows = await self._body(
            symbols=request.symbol,
            schema=schema,
            stype_in="raw_symbol",
            start=_iso(start),
            end=_iso(end),
        )
        data_revision = revision_id("databento", body, recorded=self._provenance != "live")
        bars = [self._bar(row, resolution, request.timeframe, data_revision) for row in rows]
        if request.limit is not None:
            bars = bars[-request.limit :]
        return BarSeries(
            instrument_id=resolution.instrument.id,
            contract_code=_code(resolution),
            timeframe=request.timeframe,
            data_revision=data_revision,
            provenance=self._provenance,
            bars=bars,
        )

    async def get_trades(self, request: TradesRequest) -> TradeBatch:
        resolution = await self.resolve(request.symbol)
        end = request.end or datetime.now(UTC)
        start = request.start or (end - timedelta(days=1))
        body, rows = await self._body(
            symbols=request.symbol,
            schema="trades",
            stype_in="raw_symbol",
            start=_iso(start),
            end=_iso(end),
        )
        data_revision = revision_id("databento", body, recorded=self._provenance != "live")
        trades = [
            self._trade(row, resolution, index, data_revision) for index, row in enumerate(rows)
        ]
        if request.limit is not None:
            trades = trades[-request.limit :]
        return TradeBatch(
            instrument_id=resolution.instrument.id,
            contract_code=_code(resolution),
            data_revision=data_revision,
            provenance=self._provenance,
            trades=trades,
        )

    def _require_key(self) -> None:
        if not self._api_key:
            raise missing_credential(
                "databento",
                "DATABENTO_API_KEY",
                coverage="GLBX.MDP3 definitions, OHLCV, and trades were not requested",
            )

    def _reject_continuous(self, symbol: str) -> None:
        if is_continuous_symbol(symbol):
            raise UnknownSymbolError(
                f"{symbol!r} is a continuous symbol and is not a listed contract"
            )

    def _reject_root(self, symbol: str) -> None:
        spec = self._reference.instrument(symbol)
        if spec is not None and spec.asset_class == "futures":
            raise UnknownSymbolError(
                f"{symbol!r} is a futures root; request a listed contract such as {symbol}Z6"
            )

    def _require_root(self, root: str) -> InstrumentSpec:
        spec = self._reference.instrument(root)
        if spec is None or spec.asset_class != "futures":
            raise SourceFailure(
                source="databento",
                coverage=f"root {root} is not in the versioned calendar map",
                delay="historical; not a realtime feed",
                reason="session calendar and settlement were not assumed",
                status="missing_coverage",
            )
        return spec

    async def _rows(self, **params: str) -> list[dict[str, str]]:
        _body, rows = await self._body(**params)
        return rows

    async def _body(self, **params: str) -> tuple[bytes, list[dict[str, str]]]:
        self._require_key()
        token = base64.b64encode(f"{self._api_key}:".encode()).decode("ascii")
        result = await self._transport.send(
            HttpRequest(
                method="GET",
                url=query_url(_BASE, {"dataset": _DATASET, "encoding": "csv", **params}),
                headers={"Authorization": f"Basic {token}", "Accept": "text/csv"},
            )
        )
        if result.status >= 400:
            raise SourceFailure(
                source="databento",
                coverage=f"GLBX.MDP3 {params.get('schema', 'request')} failed",
                delay="historical; not a realtime feed",
                reason=f"HTTP {result.status}",
            )
        return result.body, csv_rows(result.body, source="databento")

    def _instrument(self, spec: InstrumentSpec) -> Instrument:
        return Instrument(
            id=_id(spec.symbol),
            symbol=spec.symbol,
            name=spec.name,
            asset_class="futures",
            venue=spec.venue,
            currency=spec.currency,
            tick_size=spec.tick_size,
            tick_value=spec.tick_value,
            multiplier=spec.multiplier,
            session_calendar_id=spec.session_calendar_id,
            provenance=self._provenance,
        )

    def _contract(self, row: dict[str, str]) -> FuturesContract:
        code = row.get("raw_symbol") or ""
        parts = futures_contract_parts(code)
        if parts is None:
            raise SourceFailure(
                source="databento",
                coverage="definition row had no listed raw_symbol",
                delay="historical; not a realtime feed",
                reason="contract code was not invented",
                status="missing_coverage",
            )
        root, _listed = parts
        spec = self._require_root(root)
        known = self._reference.contract(code)
        settlement = self._settlement(root, known.settlement_type if known else None)
        tick = _optional_price(row.get("min_price_increment")) or spec.tick_size
        tick_value = _optional_price(row.get("min_price_increment_amount"))
        if tick_value is None or tick_value == 0:
            tick_value = known.tick_value if known is not None else spec.tick_value
        expiry = _expiry(row, known.expiry_date if known else None)
        return FuturesContract(
            id=_id(f"contract:{code}"),
            instrument_id=_id(root),
            root=root,
            contract_code=code,
            exchange=row.get("exchange") or spec.venue,
            contract_month=f"{expiry.year:04d}-{expiry.month:02d}",
            expiry_date=expiry,
            last_trade_date=known.last_trade_date if known else expiry,
            last_trade_time_local=known.last_trade_time_local if known else None,
            first_notice_date=known.first_notice_date if known else None,
            tick_size=tick,
            tick_value=tick_value,
            point_multiplier=(tick_value / tick) if tick != 0 else spec.multiplier,
            currency=row.get("currency") or spec.currency,
            session_calendar_id=spec.session_calendar_id,
            settlement_type=settlement,
            settlement_time_local=known.settlement_time_local if known else None,
            provenance=self._provenance,
        )

    def _settlement(self, root: str, known: SettlementType | None) -> SettlementType:
        if known is not None:
            return known
        found = {
            item.settlement_type for item in self._reference.contracts.values() if item.root == root
        }
        if len(found) == 1:
            return next(iter(found))
        raise SourceFailure(
            source="databento",
            coverage=f"settlement type for {root} is not in the versioned map",
            delay="historical; not a realtime feed",
            reason="settlement type was not assumed",
            status="missing_coverage",
        )

    def _bar(
        self,
        row: dict[str, str],
        resolution: InstrumentResolution,
        timeframe: Timeframe,
        data_revision: str,
    ) -> Bar:
        _require_field(row, "volume")
        return Bar(
            instrument_id=resolution.instrument.id,
            contract_code=_code(resolution),
            timeframe=timeframe,
            origin_time=ns_to_datetime(row["ts_event"], source="databento"),
            origin_tz=resolution.calendar.timezone,
            open=fixed_price(row.get("open"), source="databento"),
            high=fixed_price(row.get("high"), source="databento"),
            low=fixed_price(row.get("low"), source="databento"),
            close=fixed_price(row.get("close"), source="databento"),
            volume=parse_decimal(row.get("volume"), source="databento", field="volume"),
            is_complete=True,
            data_revision=data_revision,
            provenance=self._provenance,
        )

    def _trade(
        self,
        row: dict[str, str],
        resolution: InstrumentResolution,
        index: int,
        data_revision: str,
    ) -> Trade:
        _require_field(row, "size")
        raw_side = row.get("side", "")
        side: TradeSide = "buy" if raw_side == "B" else "sell" if raw_side == "A" else "unknown"
        return Trade(
            instrument_id=resolution.instrument.id,
            contract_code=_code(resolution),
            sequence=index,
            trade_time=ns_to_datetime(row["ts_event"], source="databento"),
            trade_tz=resolution.calendar.timezone,
            price=fixed_price(row.get("price"), source="databento"),
            size=parse_decimal(row.get("size"), source="databento", field="size"),
            side=side,
            venue=resolution.instrument.venue,
            data_revision=data_revision,
            provenance=self._provenance,
        )


def _require_field(row: dict[str, str], field: str) -> None:
    if row.get(field, "") == "":
        raise SourceFailure(
            source="databento",
            coverage=f"row had no {field}",
            delay="historical; not a realtime feed",
            reason=f"{field} was missing and was not invented",
            status="missing_coverage",
        )


def _optional_price(raw: str | None) -> Decimal | None:
    if raw is None or raw == "":
        return None
    return fixed_price(raw, source="databento")


def _expiry(row: dict[str, str], fallback: date | None) -> date:
    raw = row.get("expiration") or ""
    if raw:
        return ns_to_datetime(raw, source="databento").date()
    if fallback is not None:
        return fallback
    raise SourceFailure(
        source="databento",
        coverage="definition had no expiration",
        delay="historical; not a realtime feed",
        reason="expiry was not invented",
        status="missing_coverage",
    )


def _code(resolution: InstrumentResolution) -> str | None:
    if resolution.contract is None:
        return None
    return resolution.contract.contract_code


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _days_ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)
