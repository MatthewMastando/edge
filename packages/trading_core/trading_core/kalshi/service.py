"""Kalshi read-only service: public market data, fixture fallback. No order path."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import httpx

from trading_core.domain.trading_records import KalshiEventBrief, KalshiMarket, KalshiSourceRef
from trading_core.kalshi.fixture import fixture_brief, list_fixture_markets

log = logging.getLogger(__name__)

# Both hosts are documented for public market data. Neither is used for orders.
KALSHI_API_BASES: tuple[str, ...] = (
    "https://external-api.kalshi.com/trade-api/v2",
    "https://api.elections.kalshi.com/trade-api/v2",
)

_MISSING_RULES = "Settlement rules were not included in the Kalshi market payload."
_FEE_NOTES = (
    "Read-only. Kalshi trading fees follow the exchange fee schedule and are not "
    "estimated here. This workspace has no order path."
)


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
        payload = await self._get_json("/markets", {"limit": limit, "status": "open"})
        if payload is None:
            return []
        markets = payload.get("markets")
        if not isinstance(markets, list):
            return []
        out: list[KalshiMarket] = []
        for item in markets:
            if isinstance(item, dict):
                parsed = market_from_api(item)
                if parsed is not None:
                    out.append(parsed)
        return out

    async def _fetch_live_brief(self, ticker: str) -> KalshiEventBrief | None:
        safe = quote(ticker, safe="")
        payload = await self._get_json(f"/markets/{safe}", None)
        if payload is None:
            return None
        item = payload.get("market")
        if not isinstance(item, dict):
            return None
        return brief_from_api(ticker, item, retrieved_at=datetime.now(tz=UTC))

    async def _get_json(
        self, path: str, params: dict[str, str | int] | None
    ) -> dict[str, object] | None:
        for base in KALSHI_API_BASES:
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    response = await client.get(f"{base}{path}", params=params)
                if response.status_code != 200:
                    continue
                payload: object = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                log.info("Kalshi read failed for %s: %s", path, exc)
                continue
            if isinstance(payload, dict):
                return payload
        return None


def market_from_api(item: dict[str, object]) -> KalshiMarket | None:
    ticker = item.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        return None
    title = item.get("title")
    if not isinstance(title, str) or not title:
        yes_title = item.get("yes_sub_title")
        title = yes_title if isinstance(yes_title, str) and yes_title else ticker
    category = item.get("category")
    status = item.get("status")
    return KalshiMarket(
        ticker=ticker,
        title=title,
        category=category if isinstance(category, str) and category else "Event",
        status=status if isinstance(status, str) and status else "unknown",
        yes_bid=_price(item, "yes_bid_dollars", "yes_bid"),
        yes_ask=_price(item, "yes_ask_dollars", "yes_ask"),
        no_bid=_price(item, "no_bid_dollars", "no_bid"),
        no_ask=_price(item, "no_ask_dollars", "no_ask"),
        last_price=_price(item, "last_price_dollars", "last_price"),
        volume=_volume(item),
        close_time=_close_time(item.get("close_time")),
        provenance="live",
    )


def brief_from_api(
    ticker: str,
    item: dict[str, object],
    *,
    retrieved_at: datetime,
) -> KalshiEventBrief:
    rules_primary = _text(item.get("rules_primary"))
    rules_secondary = _text(item.get("rules_secondary"))
    rules = "\n\n".join(part for part in (rules_primary, rules_secondary) if part)
    yes_title = _text(item.get("yes_sub_title"))
    no_title = _text(item.get("no_sub_title"))
    title = _text(item.get("title")) or yes_title or ticker
    notional = _text(item.get("notional_value_dollars"))
    summary_parts = [title]
    if notional:
        summary_parts.append(f"Kalshi reports a contract notional of {notional} dollars.")
    fee_notes = _FEE_NOTES
    waiver = _text(item.get("fee_waiver_expiration_time"))
    if waiver:
        fee_notes = f"{fee_notes} Fee waiver expiration reported by Kalshi: {waiver}."
    return KalshiEventBrief(
        ticker=ticker,
        title=title,
        event_summary=" ".join(summary_parts),
        settlement_rules=rules or _MISSING_RULES,
        yes_scenario=yes_title or "YES outcome was not described in the Kalshi market payload.",
        no_scenario=no_title or "NO outcome was not described in the Kalshi market payload.",
        fee_notes=fee_notes,
        sources=(
            KalshiSourceRef(
                label="Kalshi market",
                url=f"https://kalshi.com/markets/{quote(ticker, safe='')}",
                retrieved_at=retrieved_at,
            ),
        ),
        provenance="live",
        is_demonstration=False,
    )


def _text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str) and value.strip():
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            return None
    return None


def _price(item: dict[str, object], dollar_key: str, legacy_key: str) -> Decimal | None:
    """Prefer Kalshi dollar strings. Legacy cent fields are scaled into dollars."""
    dollars = _decimal(item.get(dollar_key))
    if dollars is not None:
        return dollars
    legacy = _decimal(item.get(legacy_key))
    if legacy is None:
        return None
    if legacy > 1:
        return legacy / Decimal(100)
    return legacy


def _volume(item: dict[str, object]) -> int | None:
    parsed = _decimal(item.get("volume_fp"))
    if parsed is None:
        parsed = _decimal(item.get("volume"))
    if parsed is None:
        return None
    integral = parsed.to_integral_value()
    if parsed != integral:
        return None
    return int(integral)


def _close_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
