"""Market data adapter contract. Live adapters (Databento, Alpaca, Coinbase) land in Stage 3."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import Field

from trading_core.domain.common import DomainModel, Provenance, Timeframe, UtcDatetime
from trading_core.domain.instruments import FuturesContract, Instrument, SessionCalendar

if TYPE_CHECKING:
    from trading_core.domain.market import BarSeries, TradeBatch


class AdapterCapabilities(DomainModel):
    """What a provider can honestly supply. The UI surfaces this next to every result."""

    provider: str
    provenance: Provenance
    has_trades: bool = Field(description="False means exact volume profile is unavailable.")
    consolidated_equities: bool | None = Field(
        default=None, description="False for single-exchange (IEX-only) equity feeds."
    )
    coverage_note: str | None = None


class InstrumentResolution(DomainModel):
    instrument: Instrument
    contract: FuturesContract | None = Field(
        default=None, description="Set when the symbol resolved to a listed futures contract."
    )
    calendar: SessionCalendar


class BarsRequest(DomainModel):
    symbol: str = Field(description="Instrument symbol or listed contract code, e.g. 6EZ6.")
    timeframe: Timeframe
    start: UtcDatetime | None = None
    end: UtcDatetime | None = None
    limit: int | None = Field(default=None, ge=1, le=50_000)


class TradesRequest(DomainModel):
    symbol: str
    start: UtcDatetime | None = None
    end: UtcDatetime | None = None
    limit: int | None = Field(default=None, ge=1, le=1_000_000)


class UnknownSymbolError(LookupError):
    pass


@runtime_checkable
class MarketDataAdapter(Protocol):
    @property
    def capabilities(self) -> AdapterCapabilities: ...

    async def list_instruments(self) -> list[Instrument]: ...

    async def list_futures_contracts(self, root: str | None = None) -> list[FuturesContract]: ...

    async def resolve(self, symbol: str) -> InstrumentResolution: ...

    async def get_bars(self, request: BarsRequest) -> BarSeries: ...

    async def get_trades(self, request: TradesRequest) -> TradeBatch: ...
