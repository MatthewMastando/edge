"""Official research sources. A missing key is a visible failure, not a filled-in series."""

from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from trading_core.http_client import HttpRequest, query_url
from trading_core.labeling import FeedLabel, SourceFailure, missing_credential, request_was_sent
from trading_core.research.hits import ResearchHit, failure_hit
from trading_core.research.interfaces import SourceExcerpt

if TYPE_CHECKING:
    from trading_core.http_client import Transport
    from trading_core.research.fetch import SafeFetcher

_FRED = "https://api.stlouisfed.org/fred/series/observations"
_EIA = "https://api.eia.gov/v2/seriesid"
_NASS = "https://quickstats.nass.usda.gov/api/api_GET/"
_SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
_SEC_SUBMISSIONS = "https://data.sec.gov/submissions"
_CALENDARS = {
    "fed": (
        "Federal Reserve FOMC",
        "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    ),
    "ecb": (
        "ECB Governing Council",
        "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
    ),
    "boe": (
        "Bank of England MPC",
        "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates",
    ),
    "boj": (
        "Bank of Japan MPM",
        "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm",
    ),
}
_WASDE = (
    "USDA WASDE has no report-text API in this build. "
    "QuickStats is not a substitute, and crop-report prose is missing coverage."
)
# SEC fair-access is 10 requests/second. 0.12s leaves headroom for two calls in one lookup.
SEC_MIN_INTERVAL_SECONDS = 0.12
_MISSING_VALUES = {"", ".", "nan", "null", "none"}


class _Pace:
    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next:
                await asyncio.sleep(self._next - now)
            self._next = time.monotonic() + self._interval


class FredSource:
    kind = "fred"

    def __init__(self, *, api_key: str, transport: Transport) -> None:
        self._api_key = api_key.strip()
        self._transport = transport

    async def fetch(self, reference: str) -> list[SourceExcerpt]:
        hit = await self.lookup(reference)
        return [_excerpt(hit)]

    async def lookup(self, series_id: str) -> ResearchHit:
        now = datetime.now(UTC)
        if not self._api_key:
            return failure_hit(
                "fred",
                missing_credential(
                    "fred",
                    "FRED_API_KEY",
                    coverage=f"series {series_id} was not requested",
                ),
                retrieved_at=now,
                publisher="FRED",
            )
        url = query_url(
            _FRED,
            {
                "series_id": series_id,
                "api_key": self._api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "3",
            },
        )
        try:
            payload = await _json_get(self._transport, url, source="fred", headers={})
        except SourceFailure as exc:
            return failure_hit(
                "fred", exc, retrieved_at=now, publisher="FRED", external=request_was_sent(exc)
            )
        observations = payload.get("observations")
        published = _latest_published(observations)
        if published is None:
            return failure_hit(
                "fred",
                SourceFailure(
                    source="fred",
                    coverage=f"FRED series {series_id} returned no published observation",
                    delay="FRED publication lag is series-specific and was not assumed",
                    reason="missing observations are not zero",
                    status="missing_coverage",
                ),
                retrieved_at=now,
                publisher="FRED",
                external=True,
            )
        date, value = published
        text = f"FRED {series_id} observation date {date} value {value}."
        return ResearchHit(
            kind="fred",
            label=FeedLabel(
                source="fred",
                coverage=f"FRED series {series_id}; latest observation only",
                delay="FRED publication lag is series-specific and was not assumed",
                provenance="live",
            ),
            title=f"FRED {series_id}",
            text=text,
            url=f"https://fred.stlouisfed.org/series/{series_id}",
            publisher="Federal Reserve Bank of St. Louis",
            retrieved_at=now,
            external=True,
        )


class EiaSource:
    kind = "eia"

    def __init__(self, *, api_key: str, transport: Transport) -> None:
        self._api_key = api_key.strip()
        self._transport = transport

    async def fetch(self, reference: str) -> list[SourceExcerpt]:
        return [_excerpt(await self.lookup(reference))]

    async def lookup(self, series_id: str) -> ResearchHit:
        now = datetime.now(UTC)
        if not self._api_key:
            return failure_hit(
                "eia",
                missing_credential(
                    "eia",
                    "EIA_API_KEY",
                    coverage=f"series {series_id} was not requested",
                ),
                retrieved_at=now,
                publisher="EIA",
            )
        url = query_url(f"{_EIA}/{series_id}", {"api_key": self._api_key})
        try:
            payload = await _json_get(self._transport, url, source="eia", headers={})
        except SourceFailure as exc:
            return failure_hit(
                "eia", exc, retrieved_at=now, publisher="EIA", external=request_was_sent(exc)
            )
        response = payload.get("response")
        data = response.get("data") if isinstance(response, dict) else None
        row = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
        value = _published(row.get("value")) if isinstance(row, dict) else None
        if not isinstance(row, dict) or value is None:
            return failure_hit(
                "eia",
                SourceFailure(
                    source="eia",
                    coverage=f"EIA series {series_id} returned no published value",
                    delay="weekly or monthly, depending on the series; not assumed",
                    reason="missing inventory data is not zero",
                    status="missing_coverage",
                ),
                retrieved_at=now,
                publisher="EIA",
                external=True,
            )
        text = f"EIA {series_id} period {row.get('period')} value {value}."
        return ResearchHit(
            kind="eia",
            label=FeedLabel(
                source="eia",
                coverage=f"EIA series {series_id}",
                delay="series frequency as published; not a realtime inventory feed",
                provenance="live",
            ),
            title=f"EIA {series_id}",
            text=text,
            url=f"https://www.eia.gov/opendata/browser/series/{series_id}",
            publisher="U.S. Energy Information Administration",
            retrieved_at=now,
            external=True,
        )


class NassSource:
    kind = "usda"

    def __init__(self, *, api_key: str, transport: Transport) -> None:
        self._api_key = api_key.strip()
        self._transport = transport

    async def fetch(self, reference: str) -> list[SourceExcerpt]:
        return [_excerpt(await self.lookup(reference))]

    async def lookup(self, commodity: str) -> ResearchHit:
        now = datetime.now(UTC)
        if not self._api_key:
            return failure_hit(
                "usda",
                missing_credential(
                    "nass",
                    "USDA_NASS_API_KEY",
                    coverage=f"QuickStats {commodity} was not requested. {_WASDE}",
                ),
                retrieved_at=now,
                publisher="USDA NASS",
            )
        url = query_url(
            _NASS,
            {
                "key": self._api_key,
                "commodity_desc": commodity,
                "statisticcat_desc": "PRODUCTION",
                "format": "JSON",
            },
        )
        try:
            payload = await _json_get(self._transport, url, source="nass", headers={})
        except SourceFailure as exc:
            return failure_hit(
                "usda", exc, retrieved_at=now, publisher="USDA NASS", external=request_was_sent(exc)
            )
        rows = payload.get("data")
        first = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
        value = _published(first.get("Value")) if isinstance(first, dict) else None
        if not isinstance(first, dict) or value is None:
            error = payload.get("error")
            return failure_hit(
                "usda",
                SourceFailure(
                    source="nass",
                    coverage=(
                        "QuickStats returned no published production value for "
                        f"{commodity}. {_WASDE}"
                    ),
                    delay="survey release lag was not assumed",
                    reason=str(error) if error else "no published value; missing data is not zero",
                    status="missing_coverage",
                ),
                retrieved_at=now,
                publisher="USDA NASS",
                external=True,
            )
        text = (
            f"NASS QuickStats {commodity} {first.get('year')} {value} "
            f"{first.get('unit_desc')}. {_WASDE}"
        )
        return ResearchHit(
            kind="usda",
            label=FeedLabel(
                source="nass",
                coverage=f"NASS QuickStats production for {commodity}. {_WASDE}",
                delay="survey publication lag; not realtime",
                provenance="live",
            ),
            title=f"NASS {commodity}",
            text=text,
            url="https://quickstats.nass.usda.gov/",
            publisher="USDA NASS",
            retrieved_at=now,
            external=True,
        )


class SecSource:
    kind = "sec_filing"

    def __init__(
        self,
        *,
        user_agent: str,
        transport: Transport,
        min_interval: float = SEC_MIN_INTERVAL_SECONDS,
    ) -> None:
        self._user_agent = user_agent.strip()
        self._transport = transport
        self._pace = _Pace(min_interval)

    async def fetch(self, reference: str) -> list[SourceExcerpt]:
        return [_excerpt(await self.lookup(reference))]

    async def lookup(self, ticker: str) -> ResearchHit:
        now = datetime.now(UTC)
        if not self._user_agent:
            return failure_hit(
                "sec_filing",
                missing_credential(
                    "sec_edgar",
                    "SEC_EDGAR_USER_AGENT",
                    coverage=f"EDGAR filings for {ticker} were not requested",
                ),
                retrieved_at=now,
                publisher="SEC EDGAR",
            )
        headers = {"User-Agent": self._user_agent, "Accept": "application/json"}
        try:
            await self._pace.wait()
            tickers = await _json_get(
                self._transport, _SEC_TICKERS, source="sec_edgar", headers=headers
            )
            cik = _cik_for(tickers, ticker)
            if cik is None:
                raise SourceFailure(
                    source="sec_edgar",
                    coverage=f"no CIK for {ticker}",
                    delay="EDGAR index; filing body was not downloaded",
                    reason="ticker was not in company_tickers.json",
                    status="missing_coverage",
                )
            await self._pace.wait()
            submissions = await _json_get(
                self._transport,
                f"{_SEC_SUBMISSIONS}/CIK{cik}.json",
                source="sec_edgar",
                headers=headers,
            )
        except SourceFailure as exc:
            return failure_hit(
                "sec_filing",
                exc,
                retrieved_at=now,
                publisher="SEC EDGAR",
                external=request_was_sent(exc),
            )
        recent = submissions.get("filings")
        forms = ""
        if isinstance(recent, dict):
            inner = recent.get("recent")
            if isinstance(inner, dict):
                form_list = inner.get("form")
                if isinstance(form_list, list):
                    forms = ", ".join(str(item) for item in form_list[:5])
        name = submissions.get("name")
        text = (
            f"SEC EDGAR submissions for {ticker} CIK {cik} ({name}). "
            f"Recent forms: {forms or 'none listed'}. "
            "Filing document text was not downloaded in this call."
        )
        return ResearchHit(
            kind="sec_filing",
            label=FeedLabel(
                source="sec_edgar",
                coverage="EDGAR submissions index only; filing bodies are not included",
                delay="EDGAR acceptance delay; this call is rate-limited below 10 requests/second",
                provenance="live",
            ),
            title=f"SEC {ticker}",
            text=text,
            url=f"https://www.sec.gov/edgar/browse/?CIK={cik}",
            publisher="SEC EDGAR",
            retrieved_at=now,
            external=True,
        )


class CalendarSource:
    kind = "central_bank_calendar"

    def __init__(self, *, fetcher: SafeFetcher) -> None:
        self._fetcher = fetcher

    async def fetch(self, reference: str) -> list[SourceExcerpt]:
        return [_excerpt(await self.lookup(reference))]

    async def lookup(self, bank: str) -> ResearchHit:
        now = datetime.now(UTC)
        key = bank.strip().lower()
        entry = _CALENDARS.get(key)
        if entry is None:
            return failure_hit(
                "central_bank_calendar",
                SourceFailure(
                    source="central_bank_calendar",
                    coverage="supported calendars are fed, ecb, boe, and boj",
                    delay="not requested",
                    reason=f"unknown calendar {bank}",
                    status="missing_coverage",
                ),
                retrieved_at=now,
                publisher="official calendar",
            )
        name, url = entry
        try:
            document = await self._fetcher.fetch(url)
        except SourceFailure as exc:
            return failure_hit(
                "central_bank_calendar",
                exc,
                retrieved_at=now,
                publisher=name,
                external=request_was_sent(exc),
            )
        text = document.text[:1500].strip()
        if not text:
            return failure_hit(
                "central_bank_calendar",
                SourceFailure(
                    source="central_bank_calendar",
                    coverage=f"{name} page returned no calendar text",
                    delay="page retrieval time; dates were not inferred",
                    reason="empty calendar text is missing coverage, not an empty schedule",
                    status="missing_coverage",
                ),
                retrieved_at=document.retrieved_at,
                publisher=name,
                external=True,
            )
        return ResearchHit(
            kind="central_bank_calendar",
            label=FeedLabel(
                source="central_bank_calendar",
                coverage=(
                    f"{name} official calendar page. Dates are the page text, not a parsed feed."
                ),
                delay="page retrieval time; the publisher's posting lag is not estimated",
                provenance="live",
            ),
            title=name,
            text=text,
            url=document.final_url,
            publisher=name,
            retrieved_at=document.retrieved_at,
            external=True,
        )


def gap_hit(*, source: str, coverage: str, reason: str) -> ResearchHit:
    now = datetime.now(UTC)
    return ResearchHit(
        kind="release_calendar",
        label=FeedLabel(
            source=source,
            coverage=coverage,
            delay="not available",
            provenance="live",
        ),
        title=f"{source} coverage gap",
        text=reason,
        publisher=source,
        retrieved_at=now,
        status="missing_coverage",
        error=reason,
        external=False,
    )


def _excerpt(hit: ResearchHit) -> SourceExcerpt:
    return SourceExcerpt(
        id=uuid4(),
        source_id=uuid4(),
        kind=hit.kind,
        text=hit.labeled_text(),
        url=hit.url,
        published_at=hit.published_at,
        retrieved_at=hit.retrieved_at,
        provenance=hit.label.provenance,
        coverage=hit.label.coverage,
        delay=hit.label.delay,
    )


def _published(raw: object) -> str | None:
    """Return a vendor value only when one was published. Missing markers are not zero."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        return None if not math.isfinite(raw) else str(raw)
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    return None if text.lower() in _MISSING_VALUES else text


def _latest_published(observations: object) -> tuple[str, str] | None:
    if not isinstance(observations, list):
        return None
    for item in observations:
        if not isinstance(item, dict):
            continue
        value = _published(item.get("value"))
        date = item.get("date")
        if value is None or not isinstance(date, str) or not date.strip():
            continue
        return date, value
    return None


def _cik_for(payload: dict[str, object], ticker: str) -> str | None:
    target = ticker.upper()
    for value in payload.values():
        if not isinstance(value, dict):
            continue
        symbol = value.get("ticker")
        cik = value.get("cik_str")
        if isinstance(symbol, str) and symbol.upper() == target and cik is not None:
            return f"{int(str(cik)):010d}"
    return None


async def _json_get(
    transport: Transport, url: str, *, source: str, headers: dict[str, str]
) -> dict[str, object]:
    result = await transport.send(
        HttpRequest(method="GET", url=url, headers=headers, timeout_seconds=15)
    )
    if result.status == 429:
        raise SourceFailure(
            source=source,
            coverage="request was rate limited",
            delay="retry was not attempted inside this call",
            reason="HTTP 429",
            status="rate_limited",
        )
    if result.status >= 400:
        raise SourceFailure(
            source=source,
            coverage="request failed",
            delay="not applicable",
            reason=f"HTTP {result.status}",
        )
    try:
        parsed: object = json.loads(result.body)
    except json.JSONDecodeError as exc:
        raise SourceFailure(
            source=source,
            coverage="response was not JSON",
            delay="not applicable",
            reason="response was not JSON",
        ) from exc
    if not isinstance(parsed, dict):
        raise SourceFailure(
            source=source,
            coverage="response was not an object",
            delay="not applicable",
            reason="response JSON was not an object",
        )
    return cast("dict[str, object]", parsed)
