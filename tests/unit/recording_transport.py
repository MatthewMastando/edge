"""In-memory HTTP transport. Tests never open a socket."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from trading_core.http_client import HttpRequest, HttpResult


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[HttpRequest] = []
        self.routes: dict[str, HttpResult] = {}

    def add(
        self,
        path: str,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        query: str | None = None,
    ) -> None:
        key = path if query is None else f"{path}?{query}"
        self.routes[key] = HttpResult(status=status, body=body, url=path, headers=headers or {})

    async def send(self, request: HttpRequest) -> HttpResult:
        self.calls.append(request)
        parsed = urlparse(request.url)
        query = parse_qs(parsed.query)
        specific = _specific(parsed.path, query)
        result = (self.routes.get(specific) if specific else None) or self.routes.get(parsed.path)
        if result is None:
            return HttpResult(status=404, body=b"not in cassette", url=request.url, headers={})
        return HttpResult(
            status=result.status,
            body=result.body,
            url=request.url,
            headers=result.headers,
        )


def _specific(path: str, query: dict[str, list[str]]) -> str | None:
    for name in ("granularity", "schema"):
        values = query.get(name)
        if values:
            return f"{path}?{name}={values[0]}"
    return None
