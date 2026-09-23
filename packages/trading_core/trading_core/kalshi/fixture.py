"""Fixture Kalshi markets for CI and offline development."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from trading_core.domain.trading_records import KalshiEventBrief, KalshiMarket, KalshiSourceRef

FIXTURE_MARKETS: tuple[KalshiMarket, ...] = (
    KalshiMarket(
        ticker="KXFEDDECISION-25DEC-H0",
        title="Fed decision in December 2025: hold rates",
        category="Economics",
        status="open",
        yes_bid=Decimal("0.42"),
        yes_ask=Decimal("0.44"),
        no_bid=Decimal("0.56"),
        no_ask=Decimal("0.58"),
        last_price=Decimal("0.43"),
        volume=12840,
        close_time=datetime(2025, 12, 17, 19, 0, tzinfo=UTC),
        provenance="fixture",
    ),
    KalshiMarket(
        ticker="KXBTC-25DEC31-T100000",
        title="Bitcoin above $100,000 on Dec 31, 2025",
        category="Crypto",
        status="open",
        yes_bid=Decimal("0.31"),
        yes_ask=Decimal("0.33"),
        no_bid=Decimal("0.67"),
        no_ask=Decimal("0.69"),
        last_price=Decimal("0.32"),
        volume=45210,
        close_time=datetime(2025, 12, 31, 21, 0, tzinfo=UTC),
        provenance="fixture",
    ),
)

_BRIEFS: dict[str, KalshiEventBrief] = {
    "KXFEDDECISION-25DEC-H0": KalshiEventBrief(
        ticker="KXFEDDECISION-25DEC-H0",
        title="Fed decision in December 2025: hold rates",
        event_summary=(
            "Binary contract on whether the Federal Reserve holds the target range unchanged "
            "at the December 2025 FOMC meeting."
        ),
        settlement_rules=(
            "Settles to YES if the FOMC statement announces no change to the federal funds "
            "target range versus the prior meeting. Otherwise NO. Source: Kalshi contract "
            "rules and the official FOMC statement."
        ),
        yes_scenario=(
            "YES pays $1 per contract if the target range is unchanged. Implied probability "
            "is the market price, not a forecast from this workspace."
        ),
        no_scenario=(
            "NO pays $1 per contract if the Fed hikes or cuts. A hold with adjusted "
            "forward guidance still settles per the published rule text."
        ),
        fee_notes=(
            "Kalshi trading fees apply on execution (not modeled here). This module is "
            "read-only and does not submit orders."
        ),
        sources=(
            KalshiSourceRef(
                label="Kalshi market rules (fixture)",
                url="https://docs.kalshi.com/getting_started/quick_start_market_data",
                retrieved_at=datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
            ),
        ),
        provenance="fixture",
        is_demonstration=True,
    ),
    "KXBTC-25DEC31-T100000": KalshiEventBrief(
        ticker="KXBTC-25DEC31-T100000",
        title="Bitcoin above $100,000 on Dec 31, 2025",
        event_summary=(
            "Binary contract on whether a published BTC index is strictly above $100,000 "
            "at the contract's observation time."
        ),
        settlement_rules=(
            "Settles per Kalshi's published index and timestamp in the contract specification. "
            "This workspace does not apply stock-style technical analysis to the YES price."
        ),
        yes_scenario="YES if the index is above the strike at expiration per Kalshi rules.",
        no_scenario=(
            "NO if the index is at or below the strike, or if the contract is voided per rules."
        ),
        fee_notes="Read-only research module; fees are described in Kalshi's fee schedule.",
        sources=(
            KalshiSourceRef(
                label="Kalshi public market data (fixture)",
                url="https://docs.kalshi.com/getting_started/quick_start_market_data",
                retrieved_at=datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
            ),
        ),
        provenance="fixture",
        is_demonstration=True,
    ),
}


def list_fixture_markets() -> list[KalshiMarket]:
    return list(FIXTURE_MARKETS)


def fixture_brief(ticker: str) -> KalshiEventBrief | None:
    return _BRIEFS.get(ticker.upper())
