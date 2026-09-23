from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_core.data import (
    BarsRequest,
    FixtureAdapter,
    MarketDataAdapter,
    TradesRequest,
    UnknownSymbolError,
)


def test_adapter_declares_fixture_capabilities(adapter: FixtureAdapter) -> None:
    assert isinstance(adapter, MarketDataAdapter)
    caps = adapter.capabilities
    assert caps.provenance == "fixture" and caps.has_trades is True
    assert caps.consolidated_equities is False


async def test_resolve_contract_and_root(adapter: FixtureAdapter) -> None:
    resolution = await adapter.resolve("6EZ6")
    assert resolution.instrument.symbol == "6E"
    assert resolution.contract is not None and resolution.contract.contract_code == "6EZ6"
    assert resolution.calendar.id == "cme_globex_fx"

    spy = await adapter.resolve("SPY")
    assert spy.contract is None and spy.instrument.asset_class == "etf"

    with pytest.raises(UnknownSymbolError, match="futures root"):
        await adapter.resolve("6E")
    with pytest.raises(UnknownSymbolError):
        await adapter.resolve("NOPE")


async def test_bars_are_sliced_by_range_and_limit(adapter: FixtureAdapter) -> None:
    full = await adapter.get_bars(BarsRequest(symbol="ESZ6", timeframe="5m"))
    assert len(full.bars) == 2 * 276
    assert full.contract_code == "ESZ6" and full.provenance == "fixture"

    limited = await adapter.get_bars(BarsRequest(symbol="ESZ6", timeframe="5m", limit=10))
    assert limited.bars == full.bars[-10:]

    start = datetime(2026, 8, 31, 22, 0, tzinfo=UTC)
    end = datetime(2026, 8, 31, 23, 0, tzinfo=UTC)
    window = await adapter.get_bars(
        BarsRequest(symbol="ESZ6", timeframe="5m", start=start, end=end)
    )
    assert [b.origin_time for b in window.bars] == [
        b.origin_time for b in full.bars if start <= b.origin_time < end
    ]
    assert len(window.bars) == 12


async def test_trades_come_back_ordered(adapter: FixtureAdapter) -> None:
    batch = await adapter.get_trades(TradesRequest(symbol="SPY", limit=100))
    assert len(batch.trades) == 100
    assert [t.sequence for t in batch.trades] == sorted(t.sequence for t in batch.trades)
    assert batch.data_revision == adapter.manifest.data_revision


async def test_only_generated_timeframe_is_served(adapter: FixtureAdapter) -> None:
    with pytest.raises(UnknownSymbolError, match="5m"):
        await adapter.get_bars(BarsRequest(symbol="ESZ6", timeframe="1h"))
