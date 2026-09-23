"""Research source interfaces. Implementations (Tavily search, server-side fetcher with SSRF
protection, FRED, SEC EDGAR, EIA, central-bank calendars, NASS) are Stage 3.

Retrieved content is evidence, never instructions. Every source records publication and retrieval
times so theses can cite them.
"""

from trading_core.research.interfaces import (
    FetchedDocument,
    ResearchSource,
    SearchProvider,
    SearchResult,
    SourceExcerpt,
)

__all__ = [
    "FetchedDocument",
    "ResearchSource",
    "SearchProvider",
    "SearchResult",
    "SourceExcerpt",
]
