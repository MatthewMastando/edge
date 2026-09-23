"""Select market-data adapters from environment. Empty settings keep the fixture adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from trading_core.data.reference import ReferenceBook
from trading_core.data.routing import RoutingAdapter
from trading_core.domain.common import DomainModel
from trading_core.http_client import HttpxTransport, Transport

if TYPE_CHECKING:
    from pathlib import Path

    from trading_core.data.adapter import MarketDataAdapter
    from trading_core.data.fixture import FixtureAdapter

FuturesProvider = Literal["fixture", "databento"]
EquityProvider = Literal["fixture", "alpaca"]
CryptoProvider = Literal["fixture", "coinbase"]
AlpacaFeed = Literal["iex", "sip"]


class MarketConfig(DomainModel):
    futures: FuturesProvider = "fixture"
    equities: EquityProvider = "fixture"
    crypto: CryptoProvider = "fixture"
    databento_api_key: str = ""
    alpaca_key_id: str = ""
    alpaca_secret: str = ""
    alpaca_feed: AlpacaFeed = "iex"
    fixtures_dir: str = "fixtures"

    @property
    def is_fixture_only(self) -> bool:
        return self.futures == "fixture" and self.equities == "fixture" and self.crypto == "fixture"


def market_config_from_values(
    *,
    futures: str = "fixture",
    equities: str = "fixture",
    crypto: str = "fixture",
    databento_api_key: str = "",
    alpaca_key_id: str = "",
    alpaca_secret: str = "",
    alpaca_feed: str = "iex",
    fixtures_dir: str = "fixtures",
) -> MarketConfig:
    return MarketConfig(
        futures=_futures(futures),
        equities=_equities(equities),
        crypto=_crypto(crypto),
        databento_api_key=databento_api_key,
        alpaca_key_id=alpaca_key_id,
        alpaca_secret=alpaca_secret,
        alpaca_feed=_feed(alpaca_feed),
        fixtures_dir=fixtures_dir,
    )


def select_market_adapter(
    config: MarketConfig,
    *,
    fixture: FixtureAdapter,
    transport: Transport | None = None,
    fixtures_dir: Path | None = None,
) -> MarketDataAdapter:
    """Return the fixture adapter unchanged when no live provider is selected."""
    if config.is_fixture_only:
        return fixture
    directory = fixtures_dir or fixture_root_parent(fixture)
    reference = ReferenceBook.load(directory)
    return RoutingAdapter(
        config,
        fixture=fixture,
        reference=reference,
        transport=transport or HttpxTransport(),
    )


def fixture_root_parent(fixture: FixtureAdapter) -> Path:
    """Generated fixtures live in ``fixtures/generated``; calendars live in ``fixtures``."""
    root = fixture.root
    if root.name == "generated":
        return root.parent
    return root


def _futures(value: str) -> FuturesProvider:
    if value in {"", "fixture"}:
        return "fixture"
    if value == "databento":
        return "databento"
    msg = f"MARKET_DATA_FUTURES must be fixture or databento, got {value!r}"
    raise ValueError(msg)


def _equities(value: str) -> EquityProvider:
    if value in {"", "fixture"}:
        return "fixture"
    if value == "alpaca":
        return "alpaca"
    msg = f"MARKET_DATA_EQUITIES must be fixture or alpaca, got {value!r}"
    raise ValueError(msg)


def _crypto(value: str) -> CryptoProvider:
    if value in {"", "fixture"}:
        return "fixture"
    if value == "coinbase":
        return "coinbase"
    msg = f"MARKET_DATA_CRYPTO must be fixture or coinbase, got {value!r}"
    raise ValueError(msg)


def _feed(value: str) -> AlpacaFeed:
    if value in {"", "iex"}:
        return "iex"
    if value == "sip":
        return "sip"
    msg = f"ALPACA_DATA_FEED must be iex or sip, got {value!r}"
    raise ValueError(msg)
