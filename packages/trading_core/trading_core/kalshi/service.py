"""Kalshi read-only service: attempts live public API, falls back to fixtures."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from trading_core.domain.trading_records import KalshiEventBrief, KalshiMarket, KalshiSourceRef
from trading_core.kalshi.fixture import fixture_brief, list_fixture_markets

log = logging.getLogger(__name__)

KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiService:
    def __init__(self, *, use_live: bool = False) -> None:
        self._use_live = use_live

    async def list_markets(self, *, limit: int = 20) -> list[KalshiMarket]:
        if self._use_live:
            live = await self._fetch_live_markets(limit=limit)
            if live:
                return live
        return list_fixture_markets()[:limit]

    async def event_brief(self, ticker: str) -> KalshiEventBrief | None:
        if self._use_live:
            live = await self._fetch_live_brief(ticker)
            if live is not None:
                return live
        return fixture_brief(ticker)

    async def _fetch_live_markets(self, *, limit: int) -> list[KalshiMarket]:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(
                    f"{KALSHI_API_BASE}/markets",
                    params={"limit": limit, "status": "open"},
                )
                if response.status_code != 200:
                    return []
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.info("Kalshi live markets unavailable: %s", exc)
            return []

        markets = payload.get("markets")
        if not isinstance(markets, list):
            return []

        out: list[KalshiMarket] = []
        for item in markets:
            if not isinstance(item, dict):
                continue
            ticker = item.get("ticker")
            if not isinstance(ticker, str):
                continue
            out.append(
                KalshiMarket(
                    ticker=ticker,
                    title=str(item.get("title") or ticker),
                    category=str(item.get("category") or "Event"),
                    status=str(item.get("status") or "unknown"),
                    yes_bid=_optional_decimal(item.get("yes_bid")),
                    yes_ask=_optional_decimal(item.get("yes_ask")),
                    no_bid=_optional_decimal(item.get("no_bid")),
                    no_ask=_optional_decimal(item.get("no_ask")),
                    last_price=_optional_decimal(item.get("last_price")),
                    volume=int(item["volume"]) if isinstance(item.get("volume"), int) else None,
                    close_time=None,
                    provenance="live",
                )
            )
        return out

    async def _fetch_live_brief(self, ticker: str) -> KalshiEventBrief | None:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(f"{KALSHI_API_BASE}/markets/{ticker}")
                if response.status_code != 200:
                    return None
                item = response.json().get("market")
        except (httpx.HTTPError, ValueError) as exc:
            log.info("Kalshi live brief unavailable for %s: %s", ticker, exc)
            return None

        if not isinstance(item, dict):
            return None

        rules = item.get("rules_primary") or item.get("rules") or ""
        subtitle = item.get("subtitle") or ""
        return KalshiEventBrief(
            ticker=ticker,
            title=str(item.get("title") or ticker),
            event_summary=str(subtitle or item.get("title") or ""),
            settlement_rules=str(rules),
            yes_scenario="YES contracts pay $1 if the listed event resolves YES per Kalshi rules.",
            no_scenario="NO contracts pay $1 if the event resolves NO per Kalshi rules.",
            fee_notes="Fees per Kalshi fee schedule; this workspace does not trade.",
            sources=(
                KalshiSourceRef(
                    label="Kalshi API market",
                    url=f"https://kalshi.com/markets/{ticker}",
                    retrieved_at=datetime.now(tz=UTC),
                ),
            ),
            provenance="live",
            is_demonstration=False,
        )


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        if isinstance(value, str) and value:
            return Decimal(value)
    except Exception:
        return None
    return None
