"""Small HTTP client used by live adapters. Tests inject a transport and never touch the network."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None
    timeout_seconds: float = 20.0
    max_bytes: int | None = None
    pinned_ip: str | None = None


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes
    url: str
    headers: dict[str, str]
    truncated: bool = False


class Transport(Protocol):
    async def send(self, request: HttpRequest) -> HttpResult: ...


class HttpxTransport:
    """Production transport. Redirects are not followed here; callers decide.

    ``pinned_ip`` connects to that address and keeps the original host for Host and TLS.
    ``max_bytes`` stops the read once the cap is reached.
    """

    async def send(self, request: HttpRequest) -> HttpResult:
        timeout = request.timeout_seconds
        url, headers, extensions = _target(request)
        async with (
            httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client,
            client.stream(
                request.method,
                url,
                headers=headers,
                content=request.body,
                extensions=extensions,
            ) as response,
        ):
            body, truncated = await _read_limited(response, request.max_bytes)
            reported = request.url if request.pinned_ip else str(response.url)
            return HttpResult(
                status=response.status_code,
                body=body,
                url=reported,
                headers={key.lower(): value for key, value in response.headers.items()},
                truncated=truncated,
            )


def _target(request: HttpRequest) -> tuple[str, dict[str, str], dict[str, str]]:
    headers = dict(request.headers)
    if not request.pinned_ip:
        return request.url, headers, {}
    parsed = urlsplit(request.url)
    hostname = parsed.hostname or ""
    ip = request.pinned_ip
    host = f"[{ip}]" if ":" in ip else ip
    netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    url = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    default_port = 443 if parsed.scheme == "https" else 80
    if parsed.port is None or parsed.port == default_port:
        headers["Host"] = hostname
    else:
        headers["Host"] = f"{hostname}:{parsed.port}"
    return url, headers, {"sni_hostname": hostname}


async def _read_limited(response: httpx.Response, max_bytes: int | None) -> tuple[bytes, bool]:
    if max_bytes is None:
        return await response.aread(), False
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        if not chunk:
            continue
        room = max_bytes - total
        if len(chunk) > room:
            if room > 0:
                chunks.append(chunk[:room])
            return b"".join(chunks), True
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), False


def query_url(base: str, params: dict[str, str]) -> str:
    cleaned = {key: value for key, value in params.items() if value != ""}
    if not cleaned:
        return base
    return f"{base}?{urlencode(cleaned)}"
