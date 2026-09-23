"""Research sources, SSRF, and domain policy. Missing credentials stay visible failures."""

from __future__ import annotations

import json
from ipaddress import IPv4Address, IPv6Address, ip_address

import pytest

from tests.unit.recording_transport import RecordingTransport
from trading_core.http_client import HttpResult
from trading_core.labeling import SourceFailure
from trading_core.research.fetch import SafeFetcher
from trading_core.research.html_text import html_to_text
from trading_core.research.official import EiaSource, FredSource, NassSource, SecSource
from trading_core.research.policy import DomainPolicy
from trading_core.research.search import FixtureSearchProvider, TavilySearchProvider
from trading_core.research.ssrf import AddressBlockedError, check_url

_PUBLIC: list[IPv4Address | IPv6Address] = [ip_address("1.1.1.1")]


def _public(_host: str, _port: int) -> list[IPv4Address | IPv6Address]:
    return _PUBLIC


def test_ssrf_blocks_private_and_special_addresses() -> None:
    blocked = [
        "http://127.0.0.1/latest",
        "http://localhost/admin",
        "http://10.1.2.3/",
        "http://192.168.0.5/",
        "http://169.254.169.254/meta",
        "http://100.64.1.1/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "file:///etc/passwd",
        "http://user:pass@example.com/",
        "http://metadata.google.internal/",
    ]
    for url in blocked:
        with pytest.raises(AddressBlockedError):
            check_url(url, _public)
    assert check_url("https://example.com/path", _public) == "example.com"


def test_html_to_text_drops_script_and_style() -> None:
    title, text, truncated = html_to_text(
        "<html><head><title>Fed</title><script>secret()</script><style>.x{}</style></head>"
        "<body><p>Hello calendar</p></body></html>",
        limit=1000,
    )
    assert title == "Fed"
    assert "Hello calendar" in text
    assert "secret" not in text
    assert ".x" not in text
    assert truncated is False


async def test_fetcher_blocks_redirects_size_and_denied_domains() -> None:
    transport = RecordingTransport()
    transport.add(
        "/ok",
        b"<html><title>Page</title><script>nope</script><p>Visible</p></html>",
        headers={"content-type": "text/html"},
    )
    fetcher = SafeFetcher(
        transport=transport,
        policy=DomainPolicy(deny=("denied.example",)),
        max_bytes=1_000_000,
        timeout_seconds=2.5,
        resolver=_public,
    )
    document = await fetcher.fetch("https://example.com/ok")
    assert "Visible" in document.text
    assert "nope" not in document.text
    assert document.source == "fetch"
    assert transport.calls[0].timeout_seconds == 2.5

    with pytest.raises(SourceFailure, match="blocked"):
        await fetcher.fetch("http://127.0.0.1/secret")
    assert all("127.0.0.1" not in call.url for call in transport.calls)

    with pytest.raises(SourceFailure, match="domain"):
        await fetcher.fetch("https://denied.example/page")

    redirect = RecordingTransport()
    redirect.routes["/start"] = HttpResult(
        status=302,
        body=b"",
        url="/start",
        headers={"location": "http://127.0.0.1/private"},
    )
    redirect_fetcher = SafeFetcher(
        transport=redirect,
        policy=DomainPolicy(),
        resolver=_public,
    )
    with pytest.raises(SourceFailure, match=r"127\.0\.0\.1"):
        await redirect_fetcher.fetch("https://example.com/start")
    assert len(redirect.calls) == 1

    huge = RecordingTransport()
    huge.add("/big", b"abcdefghijEXTRA", headers={"content-type": "text/plain"})
    limited = SafeFetcher(
        transport=huge,
        policy=DomainPolicy(),
        max_bytes=10,
        resolver=_public,
    )
    truncated = await limited.fetch("https://example.com/big")
    assert truncated.truncated is True
    assert truncated.text == "abcdefghij"


async def test_missing_official_credentials_do_not_call_out() -> None:
    transport = RecordingTransport()
    fred = await FredSource(api_key="", transport=transport).lookup("DEXUSEU")
    eia = await EiaSource(api_key="", transport=transport).lookup("PET.WCRSTUS1.W")
    nass = await NassSource(api_key="", transport=transport).lookup("CORN")
    sec = await SecSource(user_agent="", transport=transport).lookup("AAPL")
    assert transport.calls == []
    for hit in (fred, eia, nass, sec):
        assert hit.status == "failed"
        assert hit.external is False
        assert "is not set" in (hit.error or "")
        assert "source=" in hit.labeled_text()
    assert "WASDE" in nass.label.coverage
    assert "FRED_API_KEY" in (fred.error or "")


async def test_official_payloads_keep_published_values() -> None:
    transport = RecordingTransport()
    transport.add(
        "/fred/series/observations",
        json.dumps({"observations": [{"date": "2026-09-01", "value": "1.1732"}]}).encode(),
    )
    transport.add(
        "/v2/seriesid/PET.WCRSTUS1.W",
        json.dumps({"response": {"data": [{"period": "2026-09-18", "value": "416300"}]}}).encode(),
    )
    transport.add(
        "/api/api_GET/",
        json.dumps({"data": [{"year": "2026", "Value": "15.1", "unit_desc": "BU"}]}).encode(),
    )
    fred = await FredSource(api_key="fred-key", transport=transport).lookup("DEXUSEU")
    assert fred.status == "ok" and fred.external is True
    assert "1.1732" in fred.text
    assert fred.label.source == "fred"
    eia = await EiaSource(api_key="eia-key", transport=transport).lookup("PET.WCRSTUS1.W")
    assert "416300" in eia.text
    nass = await NassSource(api_key="nass-key", transport=transport).lookup("CORN")
    assert "15.1" in nass.text
    assert "WASDE" in nass.text
    assert "api_key=fred-key" in transport.calls[0].url


async def test_sec_sends_user_agent_and_paces_requests() -> None:
    transport = RecordingTransport()
    transport.add(
        "/files/company_tickers.json",
        json.dumps({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}}).encode(),
    )
    transport.add(
        "/submissions/CIK0000320193.json",
        json.dumps(
            {"name": "Apple Inc.", "filings": {"recent": {"form": ["10-K", "8-K"]}}}
        ).encode(),
    )
    hit = await SecSource(
        user_agent="research@example.com", transport=transport, min_interval=0
    ).lookup("AAPL")
    assert hit.status == "ok"
    assert "10-K" in hit.text
    assert "filing document text was not downloaded" in hit.text.lower()
    assert len(transport.calls) == 2
    assert all(call.headers.get("User-Agent") == "research@example.com" for call in transport.calls)


async def test_search_fixture_is_demonstration_and_tavily_needs_a_key() -> None:
    rows = await FixtureSearchProvider().search("6EZ6")
    assert rows[0].provenance == "fixture"
    assert rows[0].url == "fixture://search"
    assert rows[0].delay is not None and "demonstration" in rows[0].delay
    transport = RecordingTransport()
    provider = TavilySearchProvider(api_key="", transport=transport, policy=DomainPolicy())
    with pytest.raises(SourceFailure, match="TAVILY_API_KEY") as caught:
        await provider.search("rates")
    assert caught.value.status == "missing_credential"
    assert transport.calls == []

    transport.add(
        "/search",
        json.dumps(
            {"results": [{"url": "https://example.com/a", "title": "Note", "content": "snippet"}]}
        ).encode(),
    )
    live = TavilySearchProvider(
        api_key="tvly-test", transport=transport, policy=DomainPolicy(deny=("spam.test",))
    )
    found = await live.search("rates")
    assert found[0].provenance == "live"
    assert found[0].coverage is not None and "Tavily" in found[0].coverage
    body = json.loads(transport.calls[-1].body or b"{}")
    assert body["exclude_domains"] == ["spam.test"]
    assert "tvly-test" not in transport.calls[-1].url
