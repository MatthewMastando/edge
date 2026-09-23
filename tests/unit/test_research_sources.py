"""Research sources, SSRF, and domain policy. Missing credentials stay visible failures."""

from __future__ import annotations

import json
import time
from ipaddress import IPv4Address, IPv6Address, ip_address

import pytest

from tests.unit.recording_transport import RecordingTransport
from trading_core.http_client import HttpResult
from trading_core.labeling import SourceFailure
from trading_core.research.fetch import SafeFetcher
from trading_core.research.html_text import html_to_text
from trading_core.research.official import (
    SEC_MIN_INTERVAL_SECONDS,
    CalendarSource,
    EiaSource,
    FredSource,
    NassSource,
    SecSource,
)
from trading_core.research.policy import DomainPolicy
from trading_core.research.search import FixtureSearchProvider, TavilySearchProvider
from trading_core.research.services import ResearchServices
from trading_core.research.ssrf import AddressBlockedError, check_url

_PUBLIC: list[IPv4Address | IPv6Address] = [ip_address("1.1.1.1")]


def _public(_host: str, _port: int) -> list[IPv4Address | IPv6Address]:
    return _PUBLIC


def _raise_if_resolved(_host: str, _port: int) -> list[IPv4Address | IPv6Address]:
    raise AssertionError("obfuscated addresses must not be resolved")


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
    obfuscated = [
        "http://2130706433/",
        "http://0x7f000001/",
        "http://127.1/",
        "http://0177.0.0.1/",
        "http://0x7f.0x0.0x0.0x1/",
        f"http://{int(IPv4Address('169.254.169.254'))}/",
        f"http://{int(IPv4Address('100.64.1.1'))}/",
        "http://999.1/",
        "http://app.localhost/",
        "http://printer.local/",
    ]
    for url in obfuscated:
        with pytest.raises(AddressBlockedError):
            check_url(url, _raise_if_resolved)


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
    assert transport.calls[0].max_bytes == 1_000_000
    assert transport.calls[0].pinned_ip == "1.1.1.1"

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
    assert "include_domains" not in body
    assert "tvly-test" not in transport.calls[-1].url


def test_sec_default_interval_stays_under_ten_per_second() -> None:
    assert SEC_MIN_INTERVAL_SECONDS >= 0.1
    assert 1 / SEC_MIN_INTERVAL_SECONDS < 10


async def test_fetcher_pins_one_resolution_and_times_out_dns() -> None:
    seen = {"n": 0}

    def resolver(_host: str, _port: int) -> list[IPv4Address | IPv6Address]:
        seen["n"] += 1
        if seen["n"] > 1:
            return [ip_address("127.0.0.1")]
        return [ip_address("1.1.1.1")]

    transport = RecordingTransport()
    transport.add("/ok", b"hello", headers={"content-type": "text/plain"})
    fetcher = SafeFetcher(
        transport=transport,
        policy=DomainPolicy(),
        timeout_seconds=1,
        resolver=resolver,
    )
    document = await fetcher.fetch("https://example.com/ok")
    assert document.text == "hello"
    assert seen["n"] == 1
    assert transport.calls[0].pinned_ip == "1.1.1.1"

    def slow(_host: str, _port: int) -> list[IPv4Address | IPv6Address]:
        time.sleep(1)
        return [ip_address("1.1.1.1")]

    stalled = RecordingTransport()
    limited = SafeFetcher(
        transport=stalled,
        policy=DomainPolicy(),
        timeout_seconds=0.05,
        resolver=slow,
    )
    with pytest.raises(SourceFailure, match="timed out"):
        await limited.fetch("https://example.com/ok")
    assert stalled.calls == []


async def test_missing_published_values_are_coverage_gaps() -> None:
    transport = RecordingTransport()
    transport.add(
        "/fred/series/observations",
        json.dumps(
            {
                "observations": [
                    {"date": "2026-09-01", "value": "."},
                    {"date": "2026-08-01", "value": "1.10"},
                ]
            }
        ).encode(),
        query=None,
    )
    fred = await FredSource(api_key="fred-key", transport=transport).lookup("DEXUSEU")
    assert fred.status == "ok"
    assert "2026-08-01" in fred.text
    assert "1.10" in fred.text
    assert "2026-09-01" not in fred.text

    empty = RecordingTransport()
    empty.add(
        "/fred/series/observations",
        json.dumps({"observations": [{"date": "2026-09-01", "value": "."}]}).encode(),
    )
    gap = await FredSource(api_key="fred-key", transport=empty).lookup("DEXUSEU")
    assert gap.status == "missing_coverage"
    assert gap.external is True
    assert "not zero" in (gap.error or "")
    assert "." not in gap.text

    eia_transport = RecordingTransport()
    eia_transport.add(
        "/v2/seriesid/PET.WCRSTUS1.W",
        json.dumps({"response": {"data": [{"period": "2026-09-18", "value": None}]}}).encode(),
    )
    eia = await EiaSource(api_key="eia-key", transport=eia_transport).lookup("PET.WCRSTUS1.W")
    assert eia.status == "missing_coverage"
    assert "None" not in eia.text
    assert "not zero" in (eia.error or "")

    nass_transport = RecordingTransport()
    nass_transport.add(
        "/api/api_GET/",
        json.dumps({"data": [{"year": "2026", "Value": "", "unit_desc": "BU"}]}).encode(),
    )
    nass = await NassSource(api_key="nass-key", transport=nass_transport).lookup("CORN")
    assert nass.status == "missing_coverage"
    assert "BU" not in nass.text
    assert "WASDE" in nass.label.coverage


async def test_empty_calendar_page_is_missing_coverage() -> None:
    transport = RecordingTransport()
    transport.add(
        "/monetarypolicy/fomccalendars.htm",
        b"<html><title>FOMC</title></html>",
        headers={"content-type": "text/html"},
    )
    fetcher = SafeFetcher(transport=transport, policy=DomainPolicy(), resolver=_public)
    hit = await CalendarSource(fetcher=fetcher).lookup("fed")
    assert hit.status == "missing_coverage"
    assert hit.external is True
    assert "empty calendar" in (hit.error or "")
    assert "Jan" not in hit.text


async def test_tavily_drops_denied_and_private_results() -> None:
    transport = RecordingTransport()
    transport.add(
        "/search",
        json.dumps(
            {
                "results": [
                    {"url": "https://example.com/a", "title": "Kept", "content": "ok"},
                    {"url": "https://news.spam.test/x", "title": "Denied", "content": "no"},
                    {"url": "http://2130706433/secret", "title": "Local", "content": "no"},
                ]
            }
        ).encode(),
    )
    provider = TavilySearchProvider(
        api_key="tvly-test", transport=transport, policy=DomainPolicy(deny=("spam.test",))
    )
    found = await provider.search("rates")
    assert [row.url for row in found] == ["https://example.com/a"]

    blocked = RecordingTransport()
    blocked.add(
        "/search",
        json.dumps(
            {"results": [{"url": "http://127.0.0.1/secret", "title": "Local", "content": "no"}]}
        ).encode(),
    )
    rejected = TavilySearchProvider(api_key="tvly-test", transport=blocked, policy=DomainPolicy())
    with pytest.raises(SourceFailure, match="blocked results") as caught:
        await rejected.search("rates")
    assert caught.value.status == "missing_coverage"


def _services(
    transport: RecordingTransport,
    *,
    search: FixtureSearchProvider | TavilySearchProvider | None = None,
) -> ResearchServices:
    fetcher = SafeFetcher(
        transport=transport, policy=DomainPolicy(), resolver=_public, timeout_seconds=1
    )
    return ResearchServices(
        search=search or FixtureSearchProvider(),
        fred=FredSource(api_key="fred-key", transport=transport),
        eia=EiaSource(api_key="eia-key", transport=transport),
        nass=NassSource(api_key="nass-key", transport=transport),
        sec=SecSource(user_agent="research@example.com", transport=transport, min_interval=0),
        calendars=CalendarSource(fetcher=fetcher),
        fetcher=fetcher,
    )


async def test_gather_respects_the_retrieval_budget_and_keeps_gaps() -> None:
    idle = RecordingTransport()
    search = TavilySearchProvider(api_key="tvly-test", transport=idle, policy=DomainPolicy())
    skipped, skipped_count = await _services(idle, search=search).gather(
        symbol="ZCZ6", asset_class="futures", question="crop", retrieval_budget=0
    )
    assert skipped_count == 0
    assert idle.calls == []
    assert any("WASDE" in f"{hit.text} {hit.label.coverage}" for hit in skipped)
    assert any("retrieval cap" in hit.label.coverage for hit in skipped)

    transport = RecordingTransport()
    transport.add(
        "/fred/series/observations",
        json.dumps({"observations": [{"date": "2026-08-01", "value": "1.10"}]}).encode(),
    )
    hits, external = await _services(transport).gather(
        symbol="6EZ6", asset_class="futures", question="rates", retrieval_budget=1
    )
    assert external == 1
    assert any(hit.label.source == "fred" and "1.10" in hit.text for hit in hits)
    assert any(
        hit.label.source == "central_bank_calendar" and "retrieval cap" in hit.label.coverage
        for hit in hits
    )
    assert all("fomccalendars" not in call.url for call in transport.calls)

    both = RecordingTransport()
    both.add(
        "/fred/series/observations",
        json.dumps({"observations": [{"date": "2026-08-01", "value": "1.10"}]}).encode(),
    )
    both.add(
        "/monetarypolicy/fomccalendars.htm",
        b"<html><title>FOMC</title><p>Jan 28</p></html>",
        headers={"content-type": "text/html"},
    )
    full, full_count = await _services(both).gather(
        symbol="6EZ6", asset_class="futures", question="rates", retrieval_budget=12
    )
    assert full_count == 2
    assert any("Jan 28" in hit.text for hit in full)
    assert any(hit.label.source == "fred" for hit in full)
