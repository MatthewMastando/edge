"""Search providers. The fixture implementation is the default and is labeled demonstration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from trading_core.http_client import HttpRequest
from trading_core.labeling import SourceFailure, missing_credential
from trading_core.research.interfaces import SearchResult

if TYPE_CHECKING:
    from trading_core.http_client import Transport
    from trading_core.research.policy import DomainPolicy

_TAVILY = "https://api.tavily.com/search"


class FixtureSearchProvider:
    @property
    def name(self) -> str:
        return "fixture"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        now = datetime.now(UTC)
        limit = max(1, min(max_results, 5))
        snippet = (
            f"Fixture excerpt for {query}. No live page was fetched. "
            "Treat this as demonstration context, not a market fact. "
            "source=fixture; coverage=no live retrieval; delay=none"
        )
        return [
            SearchResult(
                url="fixture://search",
                title=f"Fixture search: {query[:80]}",
                snippet=snippet,
                retrieved_at=now,
                provider="fixture",
                provenance="fixture",
                coverage="no live page was fetched",
                delay="none; demonstration search",
            )
            for _ in range(limit)
        ][:1]


class TavilySearchProvider:
    def __init__(self, *, api_key: str, transport: Transport, policy: DomainPolicy) -> None:
        self._api_key = api_key.strip()
        self._transport = transport
        self._policy = policy

    @property
    def name(self) -> str:
        return "tavily"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self._api_key:
            raise missing_credential(
                "tavily",
                "TAVILY_API_KEY",
                coverage="web search was not requested",
            )
        payload = {
            "api_key": self._api_key,
            "query": query[:300],
            "max_results": max(1, min(max_results, 5)),
            "include_domains": list(self._policy.allow),
            "exclude_domains": list(self._policy.deny),
        }
        result = await self._transport.send(
            HttpRequest(
                method="POST",
                url=_TAVILY,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                body=json.dumps(payload).encode(),
                timeout_seconds=10,
            )
        )
        if result.status >= 400:
            raise SourceFailure(
                source="tavily",
                coverage="web search failed",
                delay="request time",
                reason=f"HTTP {result.status}",
            )
        return _results(result.body)


def _results(body: bytes) -> list[SearchResult]:
    try:
        parsed: object = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SourceFailure(
            source="tavily",
            coverage="search response was not JSON",
            delay="request time",
            reason="response was not JSON",
        ) from exc
    if not isinstance(parsed, dict):
        raise SourceFailure(
            source="tavily",
            coverage="search response was not an object",
            delay="request time",
            reason="response JSON was not an object",
        )
    rows = parsed.get("results")
    if not isinstance(rows, list):
        return []
    now = datetime.now(UTC)
    found: list[SearchResult] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        title = row.get("title")
        content = row.get("content")
        if not isinstance(url, str) or not isinstance(title, str):
            continue
        published = row.get("published_date")
        found.append(
            SearchResult(
                url=url,
                title=title,
                snippet=content if isinstance(content, str) else "",
                published_at=_published(published),
                retrieved_at=now,
                provider="tavily",
                provenance="live",
                coverage="Tavily search snippet; page text is not included unless fetched",
                delay="search index delay is not disclosed by this response",
            )
        )
    return found


def _published(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
