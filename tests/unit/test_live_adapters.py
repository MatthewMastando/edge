"""Live market adapters against injected transports. No network and no invented volume."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.conftest import FIXTURES_DIR
from tests.unit.recording_transport import RecordingTransport
from trading_core.data.adapter import BarsRequest, TradesRequest
from trading_core.data.alpaca import AlpacaAdapter, FeedName
from trading_core.data.coinbase import CoinbaseAdapter
from trading_core.data.databento import DatabentoAdapter
from trading_core.data.reference import ReferenceBook
from trading_core.labeling import SourceFailure

_NS = "1765843200000000000"  # 2026-12-16T00:00:00Z
_PRICE = "1180000000"  # 1.18 in Databento 1e-9 fixed point


def _book() -> ReferenceBook:
    return ReferenceBook.load(FIXTURES_DIR)


def _definition(symbol: str = "6EZ6") -> bytes:
    return (f"raw_symbol,expiration,exchange,currency\n{symbol},{_NS},CME,USD\n").encode()


def _ohlcv(*, volume: str = "42") -> bytes:
    return (
        f"ts_event,open,high,low,close,volume\n{_NS},{_PRICE},{_PRICE},{_PRICE},{_PRICE},{volume}\n"
    ).encode()


def _trades(*, size: str = "3", side: str = "B") -> bytes:
    return f"ts_event,price,size,side\n{_NS},{_PRICE},{size},{side}\n".encode()


def _databento(transport: RecordingTransport, *, api_key: str = "db-test") -> DatabentoAdapter:
    return DatabentoAdapter(
        api_key=api_key,
        reference=_book(),
        transport=transport,
        provenance="recorded",
        replay_note="unit replay, not a live Databento call",
    )


async def test_databento_missing_key_sends_nothing() -> None:
    transport = RecordingTransport()
    adapter = _databento(transport, api_key="")
    with pytest.raises(SourceFailure, match="DATABENTO_API_KEY") as caught:
        await adapter.get_bars(BarsRequest(symbol="6EZ6", timeframe="1m"))
    assert caught.value.status == "missing_credential"
    assert transport.calls == []
    assert "not a realtime feed" in adapter.feed_label("6EZ6").delay


async def test_databento_parses_definition_bars_and_trades() -> None:
    transport = RecordingTransport()
    transport.add("/v0/timeseries.get_range", _definition(), query="schema=definition")
    transport.add("/v0/timeseries.get_range", _ohlcv(), query="schema=ohlcv-1h")
    transport.add("/v0/timeseries.get_range", _trades(side="A"), query="schema=trades")
    adapter = _databento(transport)
    resolution = await adapter.resolve("6EZ6")
    assert resolution.contract is not None
    assert resolution.contract.contract_code == "6EZ6"
    assert resolution.contract.settlement_type == "physical"
    assert resolution.contract.first_notice_date is None
    assert resolution.instrument.venue == "CME"

    bars = await adapter.get_bars(BarsRequest(symbol="6EZ6", timeframe="1h", limit=1))
    assert bars.provenance == "recorded"
    assert bars.bars[0].volume == Decimal(42)
    assert bars.bars[0].close == Decimal("1.18")
    assert bars.data_revision.startswith("recorded-databento-")

    trades = await adapter.get_trades(TradesRequest(symbol="6EZ6"))
    assert trades.trades[0].size == Decimal(3)
    assert trades.trades[0].side == "sell"
    assert "Volume is never filled in" in adapter.feed_label("6EZ6").coverage


async def test_databento_refuses_empty_volume_and_unsupported_timeframe() -> None:
    transport = RecordingTransport()
    transport.add("/v0/timeseries.get_range", _definition(), query="schema=definition")
    transport.add("/v0/timeseries.get_range", _ohlcv(volume=""), query="schema=ohlcv-1m")
    adapter = _databento(transport)
    await adapter.resolve("6EZ6")
    with pytest.raises(SourceFailure, match="volume") as caught:
        await adapter.get_bars(BarsRequest(symbol="6EZ6", timeframe="1m"))
    assert caught.value.status == "missing_coverage"
    assert "invented" in caught.value.reason

    before = len(transport.calls)
    with pytest.raises(SourceFailure, match="not aggregated"):
        await adapter.get_bars(BarsRequest(symbol="6EZ6", timeframe="5m"))
    assert len(transport.calls) == before


async def test_databento_rejects_continuous_and_unknown_root() -> None:
    transport = RecordingTransport()
    adapter = _databento(transport)
    with pytest.raises(Exception, match="continuous"):
        await adapter.resolve("ES.c.0")
    assert transport.calls == []

    transport.add("/v0/timeseries.get_range", _definition("ZZZ6"), query="schema=definition")
    with pytest.raises(SourceFailure, match="versioned calendar map"):
        await adapter.resolve("ZZZ6")


def _alpaca(
    transport: RecordingTransport,
    *,
    feed: FeedName = "iex",
    key: str = "key",
    secret: str = "secret",
) -> AlpacaAdapter:
    return AlpacaAdapter(
        key_id=key,
        secret=secret,
        reference=_book(),
        transport=transport,
        feed=feed,
        provenance="recorded",
    )


async def test_alpaca_missing_keys_send_nothing() -> None:
    transport = RecordingTransport()
    adapter = _alpaca(transport, key="", secret="")
    with pytest.raises(SourceFailure, match="ALPACA_API_KEY_ID") as caught:
        await adapter.resolve("SPY")
    assert caught.value.status == "missing_credential"
    assert transport.calls == []


async def test_alpaca_iex_is_labeled_an_approximation_and_sip_is_consolidated() -> None:
    iex = _alpaca(RecordingTransport(), feed="iex")
    sip = _alpaca(RecordingTransport(), feed="sip")
    assert "IEX-only approximation" in iex.feed_label("SPY").coverage
    assert iex.capabilities.consolidated_equities is False
    assert "Consolidated SIP" in sip.feed_label("SPY").coverage
    assert sip.capabilities.consolidated_equities is True
    assert "not verified" in sip.feed_label("SPY").delay


async def test_alpaca_parses_bars_and_does_not_invent_trade_side() -> None:
    transport = RecordingTransport()
    asset = json.dumps(
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "exchange": "ARCA"}
    ).encode()
    bars = json.dumps(
        {
            "bars": [
                {
                    "t": "2026-09-23T14:30:00Z",
                    "o": "1.00",
                    "h": "2.00",
                    "l": "0.50",
                    "c": "1.50",
                    "v": "10",
                }
            ]
        }
    ).encode()
    trades = json.dumps(
        {"trades": [{"t": "2026-09-23T14:30:01Z", "p": "1.25", "s": "4", "x": "V"}]}
    ).encode()
    transport.add("/v2/assets/SPY", asset)
    transport.add("/v2/stocks/SPY/bars", bars)
    transport.add("/v2/stocks/SPY/trades", trades)
    adapter = _alpaca(transport, feed="iex")
    series = await adapter.get_bars(BarsRequest(symbol="SPY", timeframe="1m"))
    assert series.bars[0].volume == Decimal(10)
    assert series.instrument_id is not None
    batch = await adapter.get_trades(TradesRequest(symbol="SPY"))
    assert batch.trades[0].side == "unknown"
    assert batch.trades[0].venue == "IEX"
    assert batch.trades[0].size == Decimal(4)
    assert "feed=iex" in transport.calls[-1].url

    sip_transport = RecordingTransport()
    sip_transport.add("/v2/assets/SPY", asset)
    sip_transport.add("/v2/stocks/SPY/trades", trades)
    sip = _alpaca(sip_transport, feed="sip")
    sip_batch = await sip.get_trades(TradesRequest(symbol="SPY"))
    assert sip_batch.trades[0].venue == "V"
    assert sip_batch.trades[0].side == "unknown"


async def test_alpaca_missing_volume_is_a_failure() -> None:
    transport = RecordingTransport()
    transport.add(
        "/v2/assets/SPY", json.dumps({"symbol": "SPY", "name": "SPY", "exchange": "ARCA"}).encode()
    )
    transport.add(
        "/v2/stocks/SPY/bars",
        json.dumps(
            {"bars": [{"t": "2026-09-23T14:30:00Z", "o": "1", "h": "1", "l": "1", "c": "1"}]}
        ).encode(),
    )
    adapter = _alpaca(transport)
    with pytest.raises(SourceFailure, match="volume") as caught:
        await adapter.get_bars(BarsRequest(symbol="SPY", timeframe="1d"))
    assert caught.value.status == "missing_coverage"


def _coinbase(transport: RecordingTransport) -> CoinbaseAdapter:
    cassette = json.loads((FIXTURES_DIR / "cassettes" / "coinbase-btc-usd.json").read_text())
    assert cassette["label"] == "recorded"
    assert "do not call the network" in cassette["note"]
    transport.add("/products", json.dumps(cassette["products"]).encode())
    transport.add("/products/BTC-USD", json.dumps(cassette["product"]).encode())
    transport.add(
        "/products/BTC-USD/candles",
        json.dumps(cassette["candles_5m"]).encode(),
        query="granularity=300",
    )
    transport.add(
        "/products/BTC-USD/candles",
        json.dumps(cassette["candles_1h"]).encode(),
        query="granularity=3600",
    )
    transport.add("/products/BTC-USD/trades", json.dumps(cassette["trades"]).encode())
    return CoinbaseAdapter(
        reference=_book(),
        transport=transport,
        provenance="recorded",
        replay_note=cassette["note"],
    )


async def test_coinbase_cassette_keeps_venue_base_and_quote() -> None:
    transport = RecordingTransport()
    adapter = _coinbase(transport)
    listed = await adapter.list_instruments()
    assert listed[0].symbol == "BTC-USD"
    assert listed[0].venue == "COINBASE"
    assert listed[0].base_asset == "BTC"
    assert listed[0].quote_asset == "USD"
    resolution = await adapter.resolve("BTC-USD")
    assert resolution.instrument.venue == "COINBASE"
    assert resolution.calendar.id == "crypto_24x7"
    series = await adapter.get_bars(BarsRequest(symbol="btc-usd", timeframe="5m"))
    assert series.provenance == "recorded"
    assert series.bars[0].volume == Decimal("30.38871321")
    assert "recorded" in adapter.feed_label("BTC-USD").coverage
    assert all(
        call.url.startswith("https://api.exchange.coinbase.com/") for call in transport.calls
    )


async def test_coinbase_four_hour_aggregation_is_labeled_and_sums_real_volume() -> None:
    transport = RecordingTransport()
    adapter = _coinbase(transport)
    series = await adapter.get_bars(BarsRequest(symbol="BTC-USD", timeframe="4h"))
    assert len(series.bars) == 1
    bar = series.bars[0]
    assert bar.is_complete is True
    assert bar.timeframe == "4h"
    expected = (
        Decimal("233.76757892")
        + Decimal("368.66691916")
        + Decimal("1518.97523416")
        + Decimal("538.26560065")
    )
    assert bar.volume == expected
    assert bar.origin_time == datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    assert "aggregated from 1h" in adapter.feed_label("BTC-USD").coverage
    trades = await adapter.get_trades(TradesRequest(symbol="BTC-USD", limit=2))
    assert trades.provenance == "recorded"
    assert trades.trades[0].venue == "COINBASE"
    assert {trade.side for trade in trades.trades} == {"buy", "sell"}
    assert "not a full tape" in adapter.feed_label("BTC-USD").delay
