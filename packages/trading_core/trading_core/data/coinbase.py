"""Coinbase Exchange public market data for spot crypto. No API key.

Venue and base/quote stay explicit. The public trades route is a recent page, not a full tape.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid5

from trading_core.data.adapter import (
    AdapterCapabilities,
    BarsRequest,
    InstrumentResolution,
    TradesRequest,
    UnknownSymbolError,
)
from trading_core.data.parse import (
    iso_datetime,
    json_list,
    json_object,
    parse_decimal,
    revision_id,
    unix_seconds,
)
from trading_core.domain.instruments import FuturesContract, Instrument
from trading_core.domain.market import Bar, BarSeries, Trade, TradeBatch, TradeSide
from trading_core.http_client import HttpRequest, Transport, query_url
from trading_core.labeling import FeedLabel, SourceFailure

if TYPE_CHECKING:
    from trading_core.data.reference import ReferenceBook
    from trading_core.domain.common import Provenance, Timeframe

_BASE = "https://api.exchange.coinbase.com"
_NAMESPACE = UUID("d48e0b16-7c55-4a2f-90e1-6b3f8a1c77d0")
_GRANULARITY = {"1m": "60", "5m": "300", "15m": "900", "1h": "3600", "1d": "86400"}


def _id(key: str) -> UUID:
    return uuid5(_NAMESPACE, f"coinbase:{key}")


class CoinbaseAdapter:
    def __init__(
        self,
        *,
        reference: ReferenceBook,
        transport: Transport,
        provenance: Provenance = "live",
        replay_note: str | None = None,
    ) -> None:
        self._reference = reference
        self._transport = transport
        self._provenance: Provenance = provenance
        self._replay_note = replay_note

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            provider="coinbase",
            provenance=self._provenance,
            has_trades=True,
            consolidated_equities=None,
            coverage_note=self.feed_label("*").as_note(),
        )

    def feed_label(self, symbol: str) -> FeedLabel:
        product = symbol if symbol != "*" else "BASE-QUOTE"
        coverage = (
            f"Coinbase Exchange public market data for {product}. "
            "Venue is COINBASE. Base and quote are taken from the product, not inferred. "
            "Trades are the public recent page, not a complete historical tape. "
            "4h bars are aggregated from 1h public candles and are not a native 4h feed."
        )
        if self._replay_note:
            coverage = f"{coverage} {self._replay_note}"
        return FeedLabel(
            source="coinbase",
            coverage=coverage,
            delay="public REST, near real-time; trades are not a full tape",
            provenance=self._provenance,
        )

    async def list_instruments(self) -> list[Instrument]:
        body = await self._get(f"{_BASE}/products")
        rows = json_list(body, source="coinbase")
        instruments: list[Instrument] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            product = row.get("id")
            if not isinstance(product, str) or row.get("trading_disabled") is True:
                continue
            if "-" not in product:
                continue
            instruments.append(self._instrument(product, cast("dict[str, object]", row)))
        return instruments

    async def list_futures_contracts(self, root: str | None = None) -> list[FuturesContract]:
        del root
        raise SourceFailure(
            source="coinbase",
            coverage="spot products are not listed futures",
            delay=self.feed_label("*").delay,
            reason="crypto futures were not created from the spot book",
            status="missing_coverage",
        )

    async def resolve(self, symbol: str) -> InstrumentResolution:
        product_id = _product_id(symbol)
        body = await self._get(f"{_BASE}/products/{product_id}")
        payload = json_object(body, source="coinbase")
        instrument = self._instrument(product_id, payload)
        calendar = self._reference.calendar("crypto_24x7")
        return InstrumentResolution(instrument=instrument, contract=None, calendar=calendar)

    async def get_bars(self, request: BarsRequest) -> BarSeries:
        resolution = await self.resolve(request.symbol)
        if request.timeframe == "4h":
            return await self._four_hour(request, resolution)
        granularity = _GRANULARITY.get(request.timeframe)
        if granularity is None:
            raise SourceFailure(
                source="coinbase",
                coverage=f"no public candle granularity for {request.timeframe}",
                delay=self.feed_label(request.symbol).delay,
                reason="unsupported timeframe was not invented",
                status="missing_coverage",
            )
        end = request.end or datetime.now(UTC)
        start = request.start or (end - timedelta(days=2))
        url = query_url(
            f"{_BASE}/products/{_product_id(request.symbol)}/candles",
            {"granularity": granularity, "start": _iso(start), "end": _iso(end)},
        )
        body = await self._get(url)
        rows = json_list(body, source="coinbase")
        data_revision = revision_id("coinbase", body, recorded=self._provenance != "live")
        bars = [self._candle(row, resolution, request.timeframe, data_revision) for row in rows]
        bars.sort(key=lambda bar: bar.origin_time)
        if request.limit is not None:
            bars = bars[-request.limit :]
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
        limit = str(min(request.limit or 100, 1000))
        url = query_url(f"{_BASE}/products/{_product_id(request.symbol)}/trades", {"limit": limit})
        body = await self._get(url)
        rows = json_list(body, source="coinbase")
        data_revision = revision_id("coinbase", body, recorded=self._provenance != "live")
        trades = [
            self._trade(row, resolution, index, data_revision) for index, row in enumerate(rows)
        ]
        trades.sort(key=lambda trade: trade.trade_time)
        return TradeBatch(
            instrument_id=resolution.instrument.id,
            contract_code=None,
            data_revision=data_revision,
            provenance=self._provenance,
            trades=trades,
        )

    async def _four_hour(self, request: BarsRequest, resolution: InstrumentResolution) -> BarSeries:
        hourly = await self.get_bars(request.model_copy(update={"timeframe": "1h", "limit": None}))
        grouped: dict[datetime, list[Bar]] = {}
        for bar in hourly.bars:
            bucket = bar.origin_time.replace(minute=0, second=0, microsecond=0)
            hour = bucket.hour - (bucket.hour % 4)
            start = bucket.replace(hour=hour)
            grouped.setdefault(start, []).append(bar)
        bars = [
            _aggregate(items, resolution, hourly.data_revision, self._provenance)
            for items in grouped.values()
        ]
        bars.sort(key=lambda bar: bar.origin_time)
        if request.limit is not None:
            bars = bars[-request.limit :]
        return BarSeries(
            instrument_id=resolution.instrument.id,
            contract_code=None,
            timeframe="4h",
            data_revision=hourly.data_revision,
            provenance=self._provenance,
            bars=bars,
        )

    async def _get(self, url: str) -> bytes:
        result = await self._transport.send(
            HttpRequest(
                method="GET",
                url=url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "trading-research-workspace",
                },
            )
        )
        if result.status == 404:
            raise UnknownSymbolError(f"coinbase has no product for {url}")
        if result.status >= 400:
            raise SourceFailure(
                source="coinbase",
                coverage=self.feed_label("*").coverage,
                delay=self.feed_label("*").delay,
                reason=f"HTTP {result.status}",
            )
        return result.body

    def _instrument(self, product_id: str, payload: dict[str, object]) -> Instrument:
        base, quote = _pair(product_id, payload)
        tick = parse_decimal(
            payload.get("quote_increment"), source="coinbase", field="quote_increment"
        )
        return Instrument(
            id=_id(product_id),
            symbol=product_id,
            name=str(payload.get("display_name") or product_id),
            asset_class="crypto_spot",
            venue="COINBASE",
            currency=quote,
            tick_size=tick,
            tick_value=tick,
            multiplier=Decimal(1),
            session_calendar_id="crypto_24x7",
            base_asset=base,
            quote_asset=quote,
            provenance=self._provenance,
        )

    def _candle(
        self,
        row: object,
        resolution: InstrumentResolution,
        timeframe: Timeframe,
        data_revision: str,
    ) -> Bar:
        if not isinstance(row, list) or len(row) < 6:
            raise SourceFailure(
                source="coinbase",
                coverage="candle row was short",
                delay=self.feed_label(resolution.instrument.symbol).delay,
                reason="candle volume was not invented for a short row",
                status="missing_coverage",
            )
        # Exchange candles are [time, low, high, open, close, volume].
        return Bar(
            instrument_id=resolution.instrument.id,
            contract_code=None,
            timeframe=timeframe,
            origin_time=unix_seconds(row[0], source="coinbase"),
            origin_tz="UTC",
            open=parse_decimal(row[3], source="coinbase", field="open"),
            high=parse_decimal(row[2], source="coinbase", field="high"),
            low=parse_decimal(row[1], source="coinbase", field="low"),
            close=parse_decimal(row[4], source="coinbase", field="close"),
            volume=parse_decimal(row[5], source="coinbase", field="volume"),
            is_complete=True,
            data_revision=data_revision,
            provenance=self._provenance,
        )

    def _trade(
        self,
        row: object,
        resolution: InstrumentResolution,
        index: int,
        data_revision: str,
    ) -> Trade:
        if not isinstance(row, dict):
            raise SourceFailure(
                source="coinbase",
                coverage="trade row was not an object",
                delay=self.feed_label(resolution.instrument.symbol).delay,
                reason="trade size was not invented",
                status="missing_coverage",
            )
        raw_side = str(row.get("side") or "")
        side: TradeSide = "unknown"
        if raw_side == "buy":
            side = "buy"
        elif raw_side == "sell":
            side = "sell"
        return Trade(
            instrument_id=resolution.instrument.id,
            contract_code=None,
            sequence=index,
            trade_time=iso_datetime(str(row.get("time"))),
            trade_tz="UTC",
            price=parse_decimal(row.get("price"), source="coinbase", field="price"),
            size=parse_decimal(row.get("size"), source="coinbase", field="size"),
            side=side,
            venue="COINBASE",
            data_revision=data_revision,
            provenance=self._provenance,
        )


def _product_id(symbol: str) -> str:
    if "-" not in symbol:
        raise UnknownSymbolError(
            f"{symbol!r} is not a Coinbase product id; use BASE-QUOTE such as BTC-USD"
        )
    return symbol.upper()


def _pair(product_id: str, payload: dict[str, object]) -> tuple[str, str]:
    base = payload.get("base_currency")
    quote = payload.get("quote_currency")
    if isinstance(base, str) and isinstance(quote, str) and base and quote:
        return base, quote
    left, _sep, right = product_id.partition("-")
    if left and right:
        return left, right
    raise SourceFailure(
        source="coinbase",
        coverage=f"{product_id} did not name base and quote",
        delay="public REST, near real-time; trades are not a full tape",
        reason="base and quote were not invented",
        status="missing_coverage",
    )


def _aggregate(
    items: list[Bar], resolution: InstrumentResolution, data_revision: str, provenance: Provenance
) -> Bar:
    ordered = sorted(items, key=lambda bar: bar.origin_time)
    volume = sum((bar.volume for bar in ordered), Decimal(0))
    return Bar(
        instrument_id=resolution.instrument.id,
        contract_code=None,
        timeframe="4h",
        origin_time=ordered[0].origin_time,
        origin_tz="UTC",
        open=ordered[0].open,
        high=max(bar.high for bar in ordered),
        low=min(bar.low for bar in ordered),
        close=ordered[-1].close,
        volume=volume,
        is_complete=len(ordered) == 4,
        data_revision=data_revision,
        provenance=provenance,
    )


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
