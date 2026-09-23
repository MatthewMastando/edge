"""Typed research contracts (spec section 4, item 4)."""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field

from trading_core.domain.common import DomainModel, Provenance, UtcDatetime

SourceKind = Literal[
    "web_search",
    "web_page",
    "fred",
    "sec_filing",
    "eia",
    "usda",
    "central_bank_calendar",
    "release_calendar",
]


class SearchResult(DomainModel):
    url: str
    title: str
    snippet: str
    published_at: UtcDatetime | None = None
    retrieved_at: UtcDatetime
    provider: str
    provenance: Provenance


class FetchedDocument(DomainModel):
    url: str
    final_url: str
    title: str | None = None
    text: str = Field(description="HTML converted to text and truncated to the configured limit.")
    content_type: str | None = None
    published_at: UtcDatetime | None = None
    retrieved_at: UtcDatetime
    truncated: bool = False
    provenance: Provenance


class SourceExcerpt(DomainModel):
    """A citable slice of a source, stored with an id the thesis can reference."""

    id: UUID
    source_id: UUID
    kind: SourceKind
    text: str = Field(max_length=4000)
    url: str | None = None
    published_at: UtcDatetime | None = None
    retrieved_at: UtcDatetime
    provenance: Provenance


@runtime_checkable
class SearchProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]: ...


@runtime_checkable
class ResearchSource(Protocol):
    """An official data source (FRED, SEC, EIA ...). Each call counts against the retrieval cap."""

    @property
    def kind(self) -> SourceKind: ...

    async def fetch(self, reference: str) -> list[SourceExcerpt]: ...
