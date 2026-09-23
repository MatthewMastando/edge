"""Small HTTP client used by live adapters. Tests inject a transport and never touch the network."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode

import httpx


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None
    timeout_seconds: float = 20.0


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes
    url: str
    headers: dict[str, str]


class Transport(Protocol):
    async def send(self, request: HttpRequest) -> HttpResult: ...


class HttpxTransport:
    """Production transport. Redirects are not followed here; callers decide."""

    async def send(self, request: HttpRequest) -> HttpResult:
        timeout = request.timeout_seconds
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            response = await client.request(
                request.method,
                request.url,
                headers=request.headers,
                content=request.body,
            )
        return HttpResult(
            status=response.status_code,
            body=response.content,
            url=str(response.url),
            headers={key.lower(): value for key, value in response.headers.items()},
        )


def query_url(base: str, params: dict[str, str]) -> str:
    cleaned = {key: value for key, value in params.items() if value != ""}
    if not cleaned:
        return base
    return f"{base}?{urlencode(cleaned)}"
