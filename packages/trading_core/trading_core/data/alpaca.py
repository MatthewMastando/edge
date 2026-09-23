"""Alpaca market data for equities and ETFs.

The free data feed is IEX. Consolidated SIP is used only when ALPACA_DATA_FEED=sip.
Trade prints from IEX are labeled an IEX-only volume-profile approximation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid5

from trading_core.data.adapter import (
    AdapterCapabilities,
    BarsRequest,
    InstrumentResolution,
    TradesRequest,
    UnknownSymbolError,
)
from trading_core.data.parse import iso_datetime, json_object, parse_decimal, revision_id
from trading_core.domain.instruments import FuturesContract, Instrument
from trading_core.domain.market import Bar, BarSeries, Trade, TradeBatch
from trading_core.http_client import HttpRequest, Transport, query_url
from trading_core.labeling import FeedLabel, SourceFailure, missing_credential

if TYPE_CHECKING:
    from trading_core.data.reference import ReferenceBook
    from trading_core.domain.common import Provenance, Timeframe

FeedName = Literal["iex", "sip"]
_TIMEFRAME = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "1h": "1Hour",
    "1d": "1Day",
}
_NAMESPACE = UUID("c3a91e70-5b24-4d18-9f60-1e8a7c2d44b1")
_PENNY = Decimal("0.01")


def _id(key: str) -> UUID:
    return uuid5(_NAMESPACE, f"alpaca:{key}")


class AlpacaAdapter:
    def __init__(
        self,
        *,
        key_id: str,
        secret: str,
        reference: ReferenceBook,
        transport: Transport,
        feed: FeedName = "iex",
        data_url: str = "https://data.alpaca.markets",
        trading_url: str = "https://paper-api.alpaca.markets",
        provenance: Provenance = "live",
        replay_note: str | None = None,
    ) -> None:
        self._key_id = key_id.strip()
        self._secret = secret.strip()
        self._reference = reference
        self._transport = transport
        self._feed: FeedName = feed
        self._data_url = data_url.rstrip("/")
        self._trading_url = trading_url.rstrip("/")
        self._provenance: Provenance = provenance
        self._replay_note = replay_note

    @property
    def capabilities(self) -> AdapterCapabilities:
        label = self.feed_label("*")
        return AdapterCapabilities(
            provider="alpaca",
            provenance=self._provenance,
            has_trades=bool(self._key_id and self._secret),
            consolidated_equities=self._feed == "sip",
            coverage_note=label.as_note(),
        )

    def feed_label(self, symbol: str) -> FeedLabel:
        if self._feed == "iex":
            coverage = (
                "IEX-only single-exchange bars and trades. "
                "Volume profile from these prints is an IEX-only approximation, "
                "not consolidated volume."
            )
            delay = "IEX realtime for the IEX venue only; not the consolidated tape"
        else:
            coverage = "Consolidated SIP bars and trades."
            delay = (
                "subscription-dependent; a realtime SIP entitlement is not verified by this adapter"
            )
        if symbol != "*":
            coverage = f"{coverage} Symbol {symbol}."
        if self._replay_note:
            coverage = f"{coverage} {self._replay_note}"
        if not self._key_id or not self._secret:
            coverage = f"{coverage} ALPACA_API_KEY_ID or ALPACA_API_SECRET_KEY is not set."
        return FeedLabel(
            source="alpaca",
            coverage=coverage,
            delay=delay,
            provenance=self._provenance,
        )

    async def list_instruments(self) -> list[Instrument]:
        self._require_keys()
        raise SourceFailure(
            source="alpaca",
            coverage="the full equity universe is not listed",
            delay=self.feed_label("*").delay,
            reason="resolve a symbol; an empty list would look like an empty market",
            status="missing_coverage",
        )

    async def list_futures_contracts(self, root: str | None = None) -> list[FuturesContract]:
        del root
        raise SourceFailure(
            source="alpaca",
            coverage="Alpaca equities feed has no futures definitions",
            delay=self.feed_label("*").delay,
            reason="futures were not invented from the equity feed",
            status="missing_coverage",
        )

    async def resolve(self, symbol: str) -> InstrumentResolution:
        self._require_keys()
        payload = await self._get_json(
            query_url(f"{self._trading_url}/v2/assets/{symbol}", {}),
            trading=True,
        )
        asset = _object(payload, "asset")
        name = str(asset.get("name") or symbol)
        exchange = str(asset.get("exchange") or "US")
        asset_class = _asset_class(name)
        calendar_id = "us_equity_rth"
        calendar = self._reference.calendar(calendar_id)
        instrument = Instrument(
            id=_id(symbol),
            symbol=symbol,
            name=name,
            asset_class=asset_class,
            venue=exchange,
            currency="USD",
            tick_size=_PENNY,
            tick_value=_PENNY,
            multiplier=Decimal(1),
            session_calendar_id=calendar_id,
            provenance=self._provenance,
        )
        return InstrumentResolution(instrument=instrument, contract=None, calendar=calendar)

    async def get_bars(self, request: BarsRequest) -> BarSeries:
        mapped = _TIMEFRAME.get(request.timeframe)
        if mapped is None:
            raise SourceFailure(
                source="alpaca",
                coverage=f"Alpaca has no {request.timeframe} bars",
                delay=self.feed_label(request.symbol).delay,
                reason=f"{request.timeframe} was not aggregated into a stand-in series",
                status="missing_coverage",
            )
        resolution = await self.resolve(request.symbol)
        end = request.end or datetime.now(UTC)
        start = request.start or (end - timedelta(days=5))
        params = {
            "timeframe": mapped,
            "start": _iso(start),
            "end": _iso(end),
            "feed": self._feed,
            "adjustment": "raw",
            "limit": str(request.limit or 1000),
        }
        body, payload = await self._get_body(
            query_url(f"{self._data_url}/v2/stocks/{request.symbol}/bars", params)
        )
        rows = _bar_rows(payload)
        data_revision = revision_id("alpaca", body, recorded=self._provenance != "live")
        bars = [self._bar(row, resolution, request.timeframe, data_revision) for row in rows]
        return BarSeries(
            instrument_id=resolution.instrument.id,
            contract_code=None,
            timeframe=request.timeframe,
            data_revision=data_revision,
            provenance=self._provenance,
            bars=bars,
        )

    async def get_trades(self, request: TradesRequest) -> TradeBatch:
        resolution = await self.resolve(request.symbol)
        end = request.end or datetime.now(UTC)
        start = request.start or (end - timedelta(days=1))
        params = {
            "start": _iso(start),
            "end": _iso(end),
            "feed": self._feed,
            "limit": str(request.limit or 1000),
        }
        body, payload = await self._get_body(
            query_url(f"{self._data_url}/v2/stocks/{request.symbol}/trades", params)
        )
        rows = _trade_rows(payload)
        data_revision = revision_id("alpaca", body, recorded=self._provenance != "live")
        trades = [
            self._trade(row, resolution, index, data_revision) for index, row in enumerate(rows)
        ]
        return TradeBatch(
            instrument_id=resolution.instrument.id,
            contract_code=None,
            data_revision=data_revision,
            provenance=self._provenance,
            trades=trades,
        )

    def _require_keys(self) -> None:
        if not self._key_id or not self._secret:
            raise missing_credential(
                "alpaca",
                "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY",
                coverage=self.feed_label("*").coverage,
            )

    async def _get_json(self, url: str, *, trading: bool) -> dict[str, object]:
        _body, payload = await self._get_body(url, trading=trading)
        return payload

    async def _get_body(
        self, url: str, *, trading: bool = False
    ) -> tuple[bytes, dict[str, object]]:
        self._require_keys()
        result = await self._transport.send(
            HttpRequest(
                method="GET",
                url=url,
                headers={
                    "APCA-API-KEY-ID": self._key_id,
                    "APCA-API-SECRET-KEY": self._secret,
                    "Accept": "application/json",
                },
            )
        )
        if result.status == 404:
            raise UnknownSymbolError(f"alpaca has no asset for this symbol ({result.status})")
        if result.status >= 400:
            raise SourceFailure(
                source="alpaca",
                coverage=self.feed_label("*").coverage,
                delay=self.feed_label("*").delay,
                reason=f"HTTP {result.status}",
            )
        del trading
        return result.body, json_object(result.body, source="alpaca")

    def _bar(
        self,
        row: dict[str, object],
        resolution: InstrumentResolution,
        timeframe: Timeframe,
        data_revision: str,
    ) -> Bar:
        if "v" not in row:
            raise SourceFailure(
                source="alpaca",
                coverage=self.feed_label(resolution.instrument.symbol).coverage,
                delay=self.feed_label(resolution.instrument.symbol).delay,
                reason="bar volume was missing and was not invented",
                status="missing_coverage",
            )
        return Bar(
            instrument_id=resolution.instrument.id,
            contract_code=None,
            timeframe=timeframe,
            origin_time=iso_datetime(str(row["t"])),
            origin_tz=resolution.calendar.timezone,
            open=parse_decimal(row.get("o"), source="alpaca", field="open"),
            high=parse_decimal(row.get("h"), source="alpaca", field="high"),
            low=parse_decimal(row.get("l"), source="alpaca", field="low"),
            close=parse_decimal(row.get("c"), source="alpaca", field="close"),
            volume=parse_decimal(row.get("v"), source="alpaca", field="volume"),
            trade_count=_optional_int(row.get("n")),
            vwap=_optional_decimal(row.get("vw")),
            is_complete=True,
            data_revision=data_revision,
            provenance=self._provenance,
        )

    def _trade(
        self,
        row: dict[str, object],
        resolution: InstrumentResolution,
        index: int,
        data_revision: str,
    ) -> Trade:
        if "s" not in row:
            raise SourceFailure(
                source="alpaca",
                coverage=self.feed_label(resolution.instrument.symbol).coverage,
                delay=self.feed_label(resolution.instrument.symbol).delay,
                reason="trade size was missing and was not invented",
                status="missing_coverage",
            )
        return Trade(
            instrument_id=resolution.instrument.id,
            contract_code=None,
            sequence=index,
            trade_time=iso_datetime(str(row["t"])),
            trade_tz=resolution.calendar.timezone,
            price=parse_decimal(row.get("p"), source="alpaca", field="price"),
            size=parse_decimal(row.get("s"), source="alpaca", field="size"),
            side="unknown",
            venue="IEX" if self._feed == "iex" else str(row.get("x") or "SIP"),
            data_revision=data_revision,
            provenance=self._provenance,
        )


def _asset_class(name: str) -> Literal["etf", "equity"]:
    if "ETF" in name.upper():
        return "etf"
    return "equity"


def _object(payload: dict[str, object], kind: str) -> dict[str, object]:
    if "symbol" in payload or "name" in payload:
        return payload
    raise SourceFailure(
        source="alpaca",
        coverage=f"{kind} payload was empty",
        delay="not applicable",
        reason="asset payload did not include a symbol",
        status="missing_coverage",
    )


def _bar_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    rows = payload.get("bars")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise SourceFailure(
            source="alpaca",
            coverage="bars payload was not a list",
            delay="not applicable",
            reason="bars field was not a list",
        )
    return [row for row in rows if isinstance(row, dict)]


def _trade_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    rows = payload.get("trades")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise SourceFailure(
            source="alpaca",
            coverage="trades payload was not a list",
            delay="not applicable",
            reason="trades field was not a list",
        )
    return [row for row in rows if isinstance(row, dict)]


def _optional_int(raw: object) -> int | None:
    if raw is None:
        return None
    return int(str(raw))


def _optional_decimal(raw: object) -> Decimal | None:
    if raw is None:
        return None
    return parse_decimal(raw, source="alpaca", field="vwap")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
