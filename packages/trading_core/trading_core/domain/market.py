"""Bars, trade prints and market snapshots."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from trading_core.domain.common import (
    DataRevision,
    DecimalStr,
    DomainModel,
    Provenance,
    Timeframe,
    TimezoneName,
    UtcDatetime,
)

TradeSide = Literal["buy", "sell", "unknown"]


class Bar(DomainModel):
    """One completed or forming OHLCV bar. ``origin_time`` is the bar's open time in UTC."""

    instrument_id: UUID
    contract_code: str | None = Field(
        default=None, description="Listed contract code for futures bars; null otherwise."
    )
    timeframe: Timeframe
    origin_time: UtcDatetime
    origin_tz: TimezoneName
    open: DecimalStr
    high: DecimalStr
    low: DecimalStr
    close: DecimalStr
    volume: DecimalStr = Field(description="Total traded size in the bar; decimals for crypto.")
    trade_count: int | None = Field(default=None, ge=0)
    vwap: DecimalStr | None = None
    is_complete: bool = Field(
        default=True, description="Only completed bars may produce confirmed signals."
    )
    data_revision: DataRevision
    provenance: Provenance


class Trade(DomainModel):
    """A single trade print. ``side`` is the aggressor side only when the venue reports it;
    price-up/price-down volume is never labeled as buy/sell."""

    instrument_id: UUID
    contract_code: str | None = None
    sequence: int = Field(ge=0, description="Monotonic sequence within the snapshot.")
    trade_time: UtcDatetime
    trade_tz: TimezoneName
    price: DecimalStr
    size: DecimalStr
    side: TradeSide = "unknown"
    venue: str
    data_revision: DataRevision
    provenance: Provenance


class MarketSnapshot(DomainModel):
    """An immutable capture of bars and/or trades stored as Parquet. Every TA feature references
    the snapshot it was computed from through ``data_revision``."""

    id: UUID
    instrument_id: UUID
    contract_code: str | None = None
    timeframe: Timeframe | None = Field(
        default=None, description="Timeframe for bar snapshots; null for trade snapshots."
    )
    kind: Literal["bars", "trades"]
    range_start: UtcDatetime
    range_end: UtcDatetime
    as_of: UtcDatetime = Field(description="Time the capture was taken.")
    provider: str = Field(examples=["fixture", "databento", "alpaca", "coinbase"])
    provenance: Provenance
    data_revision: DataRevision
    storage_key: str = Field(description="Object-store key of the Parquet file.")
    row_count: int = Field(ge=0)
    content_hash: str = Field(
        min_length=16, description="SHA-256 over the canonical row encoding; detects drift."
    )
    coverage_note: str | None = Field(
        default=None,
        description="e.g. 'IEX-only approximation' for single-exchange equity trades.",
    )


class BarSeries(DomainModel):
    """A contiguous run of bars from one snapshot."""

    instrument_id: UUID
    contract_code: str | None = None
    timeframe: Timeframe
    data_revision: DataRevision
    provenance: Provenance
    bars: list[Bar]


class TradeBatch(DomainModel):
    """Trade prints from one snapshot, ordered by ``sequence``."""

    instrument_id: UUID
    contract_code: str | None = None
    data_revision: DataRevision
    provenance: Provenance
    trades: list[Trade]
