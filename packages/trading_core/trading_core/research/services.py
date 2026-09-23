"""Research services selected by environment. Fixture mode leaves this object unset."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from trading_core.labeling import FeedLabel, SourceFailure, request_was_sent
from trading_core.research.hits import ResearchHit, failure_hit
from trading_core.research.official import (
    CalendarSource,
    EiaSource,
    FredSource,
    NassSource,
    SecSource,
    gap_hit,
)

if TYPE_CHECKING:
    from trading_core.domain.common import Provenance
    from trading_core.research.fetch import SafeFetcher
    from trading_core.research.interfaces import SearchProvider, SourceKind

_AG = {"ZC": "CORN", "ZS": "SOYBEANS", "ZW": "WHEAT", "KE": "WHEAT", "ZM": "SOYBEANS"}
_MAX_GATHER = 3


class ResearchServices:
    def __init__(
        self,
        *,
        search: SearchProvider,
        fred: FredSource,
        eia: EiaSource,
        nass: NassSource,
        sec: SecSource,
        calendars: CalendarSource,
        fetcher: SafeFetcher,
    ) -> None:
        self.search = search
        self.fred = fred
        self.eia = eia
        self.nass = nass
        self.sec = sec
        self.calendars = calendars
        self.fetcher = fetcher

    async def search_hits(
        self, query: str, *, max_results: int = 5
    ) -> tuple[list[ResearchHit], int]:
        try:
            rows = await self.search.search(query, max_results=max_results)
        except SourceFailure as exc:
            now = _now()
            sent = request_was_sent(exc)
            return (
                [
                    failure_hit(
                        "web_search",
                        exc,
                        retrieved_at=now,
                        publisher=self.search.name,
                        external=sent,
                    )
                ],
                1 if sent else 0,
            )
        external = 0 if self.search.name == "fixture" else 1
        hits = [
            ResearchHit(
                kind="web_search",
                label=_search_label(row.provider, row.provenance, row.coverage, row.delay),
                title=row.title,
                text=row.snippet,
                url=None if row.url.startswith("fixture://") else row.url,
                publisher=row.provider,
                published_at=row.published_at,
                retrieved_at=row.retrieved_at,
                external=external == 1,
            )
            for row in rows
        ]
        return hits, external

    async def gather(
        self,
        *,
        symbol: str,
        asset_class: str,
        question: str,
        retrieval_budget: int = _MAX_GATHER,
    ) -> tuple[list[ResearchHit], int]:
        """Gather context without exceeding the run's remaining retrieval budget.

        Coverage-gap notes are still returned when a live call is skipped.
        """
        cap = min(_MAX_GATHER, max(0, retrieval_budget))
        hits: list[ResearchHit] = []
        external = 0
        if cap > 0:
            found, used = await self.search_hits(f"{symbol} {question}"[:300], max_results=3)
            hits.extend(found)
            external += used
        else:
            hits.append(_skipped("web_search", "web search"))
        for kind, reference in _plan(symbol, asset_class):
            if kind == "gap":
                hits.append(gap_hit(source="research", coverage=reference, reason=reference))
                continue
            if external >= cap:
                hits.append(_skipped(kind, reference))
                continue
            hit = await self._one(kind, reference)
            hits.append(hit)
            if hit.external:
                external += 1
        return hits, external

    async def _one(self, kind: str, reference: str) -> ResearchHit:
        if kind == "fred":
            hit = await self.fred.lookup(reference)
        elif kind == "eia":
            hit = await self.eia.lookup(reference)
        elif kind == "usda":
            hit = await self.nass.lookup(reference)
        elif kind == "sec_filing":
            hit = await self.sec.lookup(reference)
        elif kind == "central_bank_calendar":
            hit = await self.calendars.lookup(reference)
        elif kind == "gap":
            hit = gap_hit(source="research", coverage=reference, reason=reference)
        else:
            hit = failure_hit(
                "release_calendar",
                SourceFailure(
                    source="research",
                    coverage=kind,
                    delay="not requested",
                    reason="unknown source",
                    status="missing_coverage",
                ),
                retrieved_at=_now(),
                publisher="research",
            )
        return hit


def _skipped(kind: str, reference: str) -> ResearchHit:
    return ResearchHit(
        kind=_source_kind(kind),
        label=FeedLabel(
            source=kind,
            coverage=f"{kind} {reference} was not requested because the retrieval cap was reached",
            delay="not requested",
            provenance="live",
        ),
        title=f"{kind} not retrieved",
        text="external retrieval cap reached; no value was invented",
        publisher=kind,
        retrieved_at=_now(),
        status="missing_coverage",
        error="external retrieval cap reached; no value was invented",
        external=False,
    )


def _source_kind(kind: str) -> SourceKind:
    kinds: dict[str, SourceKind] = {
        "fred": "fred",
        "eia": "eia",
        "usda": "usda",
        "sec_filing": "sec_filing",
        "central_bank_calendar": "central_bank_calendar",
        "web_search": "web_search",
        "web_page": "web_page",
    }
    return kinds.get(kind, "release_calendar")


def _plan(symbol: str, asset_class: str) -> list[tuple[str, str]]:
    root = symbol[:-2] if len(symbol) > 2 else symbol
    steps: list[tuple[str, str]]
    if root in _AG or symbol in _AG:
        commodity = _AG.get(root, _AG.get(symbol, "CORN"))
        steps = [
            ("usda", commodity),
            ("gap", "WASDE report text is not available from QuickStats."),
        ]
    elif asset_class == "crypto_spot" or "-" in symbol:
        steps = [
            (
                "gap",
                "No on-chain or project-document source is configured for spot crypto. "
                "That coverage is missing.",
            )
        ]
    elif asset_class in {"etf", "equity"}:
        steps = [("sec_filing", symbol), ("central_bank_calendar", "fed")]
    elif root in {"CL", "NG", "HO", "RB"}:
        steps = [("eia", "PET.WCRSTUS1.W"), ("central_bank_calendar", "fed")]
    elif root in {"6E", "6B", "6J", "6A", "6C"}:
        steps = [("fred", "DEXUSEU"), ("central_bank_calendar", "fed")]
    elif root in {"GC", "SI", "HG"}:
        steps = [("fred", "GOLDAMGBD228NLBM"), ("central_bank_calendar", "fed")]
    elif root in {"ES", "NQ", "YM", "RTY"}:
        steps = [("fred", "DFF"), ("central_bank_calendar", "fed")]
    else:
        steps = [("central_bank_calendar", "fed")]
    return steps


def _search_label(
    provider: str, provenance: str, coverage: str | None, delay: str | None
) -> FeedLabel:
    proven: Provenance = "fixture"
    if provenance == "live":
        proven = "live"
    elif provenance == "recorded":
        proven = "recorded"
    return FeedLabel(
        source=provider,
        coverage=coverage or "search snippet",
        delay=delay or "not reported",
        provenance=proven,
    )


def _now() -> datetime:
    return datetime.now(UTC)
