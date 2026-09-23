"""Production transport: pin the checked address and stop reading at the size cap."""

from __future__ import annotations

import asyncio

from trading_core.http_client import HttpRequest, HttpxTransport


async def test_httpx_transport_pins_the_address_and_stops_at_max_bytes() -> None:
    seen: dict[str, bytes] = {}

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        seen["request"] = await reader.read(4096)
        body = b"abcdefghijEXTRA"
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 15\r\nConnection: close\r\n\r\n" + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    bound = server.sockets
    if not bound:
        raise RuntimeError("test server did not bind")
    port = int(bound[0].getsockname()[1])
    try:
        result = await HttpxTransport().send(
            HttpRequest(
                method="GET",
                url=f"http://example.com:{port}/path",
                pinned_ip="127.0.0.1",
                max_bytes=10,
                timeout_seconds=2,
            )
        )
    finally:
        server.close()
        await server.wait_closed()
    assert result.truncated is True
    assert result.body == b"abcdefghij"
    assert result.url == f"http://example.com:{port}/path"
    request = seen["request"].lower()
    assert b"host: example.com:" in request
    assert b"127.0.0.1" not in request.split(b"\r\n", maxsplit=1)[0]
