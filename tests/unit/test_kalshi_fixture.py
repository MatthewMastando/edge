"""Kalshi fixture module (no network)."""

from __future__ import annotations

import pytest

from trading_core.kalshi.fixture import fixture_brief, list_fixture_markets
from trading_core.kalshi.service import KalshiService


@pytest.mark.asyncio
async def test_fixture_markets_and_brief() -> None:
    markets = list_fixture_markets()
    assert len(markets) >= 1
    service = KalshiService(use_live=False)
    listed = await service.list_markets()
    assert listed[0].provenance == "fixture"
    brief = await service.event_brief(markets[0].ticker)
    assert brief is not None
    assert brief.is_demonstration is True
    assert "technical analysis" not in brief.settlement_rules.lower()
    assert fixture_brief("missing") is None
