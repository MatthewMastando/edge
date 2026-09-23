"""Server-side page fetch with SSRF checks, domain policy, and size and time limits."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from trading_core.http_client import HttpRequest
from trading_core.labeling import FeedLabel, SourceFailure
from trading_core.research.html_text import html_to_text
from trading_core.research.interfaces import FetchedDocument
from trading_core.research.ssrf import AddressBlockedError, Resolver, check_url, default_resolver

if TYPE_CHECKING:
    from trading_core.http_client import Transport
    from trading_core.research.policy import DomainPolicy

_LABEL = FeedLabel(
    source="fetch",
    coverage="server-side fetch of one public URL; HTML reduced to text",
    delay="retrieved at request time",
    provenance="live",
)


class SafeFetcher:
    def __init__(
        self,
        *,
        transport: Transport,
        policy: DomainPolicy,
        max_bytes: int = 1_000_000,
        timeout_seconds: float = 10.0,
        max_redirects: int = 3,
        resolver: Resolver = default_resolver,
    ) -> None:
        self._transport = transport
        self._policy = policy
        self._max_bytes = max_bytes
        self._timeout = timeout_seconds
        self._max_redirects = max_redirects
        self._resolver = resolver

    async def fetch(self, url: str) -> FetchedDocument:
        current = url
        for _hop in range(self._max_redirects + 1):
            self._permit(current)
            result = await self._transport.send(
                HttpRequest(
                    method="GET",
                    url=current,
                    headers={
                        "Accept": "text/html,application/json;q=0.9,*/*;q=0.1",
                        "User-Agent": "trading-research-workspace",
                    },
                    timeout_seconds=self._timeout,
                )
            )
            location = result.headers.get("location")
            if result.status in {301, 302, 303, 307, 308} and location:
                current = urljoin(current, location)
                continue
            if result.status >= 400:
                raise SourceFailure(
                    source="fetch",
                    coverage=_LABEL.coverage,
                    delay=_LABEL.delay,
                    reason=f"HTTP {result.status}",
                )
            body = result.body[: self._max_bytes]
            truncated = len(result.body) > self._max_bytes
            text_body = body.decode("utf-8", errors="replace")
            content_type = result.headers.get("content-type", "")
            if "html" in content_type or text_body.lstrip().startswith("<"):
                title, text, text_truncated = html_to_text(text_body, limit=self._max_bytes)
            else:
                title, text, text_truncated = None, text_body[: self._max_bytes], truncated
            return FetchedDocument(
                url=url,
                final_url=result.url or current,
                title=title,
                text=text,
                content_type=content_type or None,
                retrieved_at=datetime.now(UTC),
                truncated=truncated or text_truncated,
                provenance="live",
                source="fetch",
                coverage=_LABEL.coverage,
                delay=_LABEL.delay,
            )
        raise SourceFailure(
            source="fetch",
            coverage=_LABEL.coverage,
            delay=_LABEL.delay,
            reason="too many redirects",
        )

    def _permit(self, url: str) -> None:
        try:
            host = check_url(url, self._resolver)
        except AddressBlockedError as exc:
            raise SourceFailure(
                source="fetch",
                coverage="request blocked before any connection",
                delay="not requested",
                reason=str(exc),
                status="failed",
            ) from exc
        refusal = self._policy.refusal(host)
        if refusal is not None:
            raise SourceFailure(
                source="fetch",
                coverage="request blocked by the domain allow/deny list",
                delay="not requested",
                reason=refusal,
                status="failed",
            )
