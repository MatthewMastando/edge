"""Route a symbol to the configured futures, equity, or spot-crypto adapter.

When every leg is fixture, callers should keep the FixtureAdapter itself so the fixture path
does not change. This router is only built once a leg is set to a live provider.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from trading_core.data.adapter import (
    AdapterCapabilities,
    BarsRequest,
    InstrumentResolution,
    TradesRequest,
    UnknownSymbolError,
)
from trading_core.data.alpaca import AlpacaAdapter
from trading_core.data.coinbase import CoinbaseAdapter
from trading_core.data.databento import DatabentoAdapter
from trading_core.data.parse import futures_contract_parts, is_continuous_symbol
from trading_core.labeling import FeedLabel

if TYPE_CHECKING:
    from trading_core.data.factory import MarketConfig
    from trading_core.data.fixture import FixtureAdapter
    from trading_core.data.reference import ReferenceBook
    from trading_core.domain.instruments import FuturesContract, Instrument
    from trading_core.domain.market import BarSeries, TradeBatch
    from trading_core.http_client import Transport


class RoutingAdapter:
    def __init__(
        self,
        config: MarketConfig,
        *,
        fixture: FixtureAdapter,
        reference: ReferenceBook,
        transport: Transport,
    ) -> None:
        self._config = config
        self._fixture = fixture
        self._futures = self._build_futures(config, reference, transport)
        self._equities = self._build_equities(config, reference, transport)
        self._crypto = self._build_crypto(config, reference, transport)

    @property
    def capabilities(self) -> AdapterCapabilities:
        label = self._summary_label()
        iex = self._config.equities == "alpaca" and self._config.alpaca_feed == "iex"
        sip = self._config.equities == "alpaca" and self._config.alpaca_feed == "sip"
        consolidated: bool | None = False if iex else True if sip else None
        return AdapterCapabilities(
            provider="routing",
            provenance="live",
            has_trades=True,
            consolidated_equities=consolidated,
            coverage_note=label.as_note(),
        )

    def feed_label(self, symbol: str) -> FeedLabel:
        return self._leg(symbol).feed_label(symbol)

    async def list_instruments(self) -> list[Instrument]:
        rows: list[Instrument] = []
        rows.extend(await self._futures.list_instruments())
        if self._config.equities == "fixture":
            rows.extend(
                item
                for item in await self._fixture.list_instruments()
                if item.asset_class in {"equity", "etf"}
            )
        if self._config.crypto == "coinbase":
            rows.extend(await self._crypto.list_instruments())
        elif self._config.crypto == "fixture":
            rows.extend(
                item
                for item in await self._fixture.list_instruments()
                if item.asset_class == "crypto_spot"
            )
        return rows

    async def list_futures_contracts(self, root: str | None = None) -> list[FuturesContract]:
        return await self._futures.list_futures_contracts(root)

    async def resolve(self, symbol: str) -> InstrumentResolution:
        return await self._leg(symbol).resolve(symbol)

    async def get_bars(self, request: BarsRequest) -> BarSeries:
        return await self._leg(request.symbol).get_bars(request)

    async def get_trades(self, request: TradesRequest) -> TradeBatch:
        return await self._leg(request.symbol).get_trades(request)

    def _leg(
        self, symbol: str
    ) -> FixtureAdapter | DatabentoAdapter | AlpacaAdapter | CoinbaseAdapter:
        if is_continuous_symbol(symbol):
            raise UnknownSymbolError(
                f"{symbol!r} is a continuous symbol and is not a listed contract"
            )
        if "-" in symbol:
            return self._crypto
        if futures_contract_parts(symbol) is not None or self._is_root(symbol):
            return self._futures
        return self._equities

    def _is_root(self, symbol: str) -> bool:
        spec = self._fixture.manifest.instruments
        return any(item.symbol == symbol and item.asset_class == "futures" for item in spec)

    def _summary_label(self) -> FeedLabel:
        parts = [
            f"futures={self._config.futures}",
            f"equities={self._config.equities}",
            f"crypto={self._config.crypto}",
        ]
        if self._config.equities == "alpaca":
            parts.append(f"alpaca_feed={self._config.alpaca_feed}")
        gaps: list[str] = []
        if self._config.futures == "databento" and not self._config.databento_api_key:
            gaps.append("futures unavailable until DATABENTO_API_KEY is set")
        if self._config.equities == "alpaca" and not (
            self._config.alpaca_key_id and self._config.alpaca_secret
        ):
            gaps.append("equities unavailable until Alpaca keys are set")
        coverage = "Each result carries its own source, coverage, and delay. " + "; ".join(parts)
        if gaps:
            coverage = f"{coverage}. " + "; ".join(gaps)
        return FeedLabel(
            source="routing",
            coverage=coverage,
            delay="per source; see the result label",
            provenance="live",
        )

    def _build_futures(
        self, config: MarketConfig, reference: ReferenceBook, transport: Transport
    ) -> FixtureAdapter | DatabentoAdapter:
        if config.futures == "fixture":
            return self._fixture
        return DatabentoAdapter(
            api_key=config.databento_api_key,
            reference=reference,
            transport=transport,
        )

    def _build_equities(
        self, config: MarketConfig, reference: ReferenceBook, transport: Transport
    ) -> FixtureAdapter | AlpacaAdapter:
        if config.equities == "fixture":
            return self._fixture
        return AlpacaAdapter(
            key_id=config.alpaca_key_id,
            secret=config.alpaca_secret,
            reference=reference,
            transport=transport,
            feed=config.alpaca_feed,
        )

    def _build_crypto(
        self, config: MarketConfig, reference: ReferenceBook, transport: Transport
    ) -> FixtureAdapter | CoinbaseAdapter:
        if config.crypto == "fixture":
            return self._fixture
        return CoinbaseAdapter(reference=reference, transport=transport)
