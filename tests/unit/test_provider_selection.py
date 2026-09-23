"""Empty environment keeps the fixture adapter and skips live research."""

from __future__ import annotations

import pytest

from tests.conftest import FIXTURES_DIR
from tests.unit.recording_transport import RecordingTransport
from trading_core.data.adapter import BarsRequest
from trading_core.data.factory import market_config_from_values, select_market_adapter
from trading_core.data.fixture import FixtureAdapter
from trading_core.labeling import SourceFailure
from trading_core.research.factory import build_research_services, research_config_from_values


def test_empty_settings_keep_the_fixture_path(adapter: FixtureAdapter) -> None:
    market = market_config_from_values()
    assert market.is_fixture_only is True
    selected = select_market_adapter(market, fixture=adapter)
    assert selected is adapter
    assert build_research_services(research_config_from_values()) is None


def test_blank_provider_names_stay_on_fixtures() -> None:
    market = market_config_from_values(futures="", equities="", crypto="", alpaca_feed="")
    assert market.futures == "fixture"
    assert market.equities == "fixture"
    assert market.crypto == "fixture"
    assert market.alpaca_feed == "iex"
    research = research_config_from_values(search_provider="")
    assert research.is_fixture_only is True


async def test_databento_without_a_key_fails_instead_of_using_fixtures(
    adapter: FixtureAdapter,
) -> None:
    transport = RecordingTransport()
    market = market_config_from_values(futures="databento", databento_api_key="")
    selected = select_market_adapter(
        market,
        fixture=adapter,
        transport=transport,
        fixtures_dir=FIXTURES_DIR,
    )
    assert selected is not adapter
    with pytest.raises(SourceFailure, match="DATABENTO_API_KEY") as caught:
        await selected.get_bars(BarsRequest(symbol="6EZ6", timeframe="1m"))
    assert caught.value.status == "missing_credential"
    assert transport.calls == []
    note = selected.capabilities.coverage_note or ""
    assert "DATABENTO_API_KEY" in note


async def test_fixture_equity_leg_still_serves_spy(adapter: FixtureAdapter) -> None:
    market = market_config_from_values(futures="databento")
    selected = select_market_adapter(
        market,
        fixture=adapter,
        transport=RecordingTransport(),
        fixtures_dir=FIXTURES_DIR,
    )
    resolution = await selected.resolve("SPY")
    assert resolution.instrument.provenance == "fixture"
    assert resolution.instrument.asset_class == "etf"
