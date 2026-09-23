"""Kalshi fixture module and read-only payload parsing (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading_api.routes.kalshi import router
from trading_core.kalshi.fixture import fixture_brief, list_fixture_markets
from trading_core.kalshi.service import KalshiService, brief_from_api, market_from_api


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


def test_kalshi_routes_are_read_only() -> None:
    for route in router.routes:
        methods: set[str] = getattr(route, "methods", set())
        assert methods <= {"GET", "HEAD"}


def test_live_prices_use_dollar_fields_and_rules_are_not_invented() -> None:
    market = market_from_api(
        {
            "ticker": "KXTEST-25",
            "title": "Test event",
            "status": "active",
            "yes_bid_dollars": "0.5600",
            "yes_bid": 99,
            "yes_ask_dollars": "0.5700",
            "no_bid_dollars": "0.4300",
            "no_ask_dollars": "0.4400",
            "last_price_dollars": "0.5600",
            "volume_fp": "10.00",
            "close_time": "2026-12-31T21:00:00Z",
        }
    )
    assert market is not None
    assert market.yes_bid == Decimal("0.5600")
    assert market.last_price == Decimal("0.5600")
    assert market.volume == 10
    assert market.provenance == "live"

    legacy = market_from_api({"ticker": "KXLEGACY", "title": "Legacy", "yes_bid": 42})
    assert legacy is not None
    assert legacy.yes_bid == Decimal("0.42")

    brief = brief_from_api(
        "KXTEST-25",
        {
            "title": "Test event",
            "yes_sub_title": "Above the strike",
            "no_sub_title": "At or below the strike",
            "rules_primary": "Settles from the official index print.",
            "rules_secondary": "Void if the index is unpublished.",
            "notional_value_dollars": "1.0000",
        },
        retrieved_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    assert brief.yes_scenario == "Above the strike"
    assert brief.no_scenario == "At or below the strike"
    assert "official index print" in brief.settlement_rules
    assert "rsi" not in brief.settlement_rules.lower()
    assert "moving average" not in brief.event_summary.lower()
    assert brief.is_demonstration is False

    empty = brief_from_api(
        "KXEMPTY",
        {"title": "No rules"},
        retrieved_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    assert "not included" in empty.settlement_rules
    assert "not described" in empty.yes_scenario
