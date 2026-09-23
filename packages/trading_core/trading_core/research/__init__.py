"""Research sources: fixture or Tavily search, SSRF-protected fetch, FRED, SEC EDGAR, EIA,
central-bank calendars, and NASS QuickStats.

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
