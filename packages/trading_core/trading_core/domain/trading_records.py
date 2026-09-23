"""CSV import, personal trading history, and Kalshi read-only contracts."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from trading_core.domain.common import DecimalStr, DomainModel, Provenance, UtcDatetime

ImportField = Literal[
    "symbol",
    "side",
    "quantity",
    "price",
    "fees",
    "fill_time",
    "currency",
    "contract_code",
    "venue",
    "fill_tz",
]

IMPORT_FIELDS: tuple[ImportField, ...] = (
    "symbol",
    "side",
    "quantity",
    "price",
    "fees",
    "fill_time",
    "currency",
    "contract_code",
    "venue",
    "fill_tz",
)


class CsvColumnMapping(DomainModel):
    """Maps logical fill fields to CSV header names. Unmapped optional fields use defaults."""

    preset_name: str | None = Field(default=None, max_length=120)
    columns: dict[ImportField, str]
    default_currency: str = Field(default="USD", max_length=8)
    default_fill_tz: str = Field(default="America/New_York", max_length=64)


class ImportPreset(DomainModel):
    name: str = Field(max_length=120)
    mapping: CsvColumnMapping


class ImportRowIssue(DomainModel):
    source_row_number: int = Field(ge=1)
    severity: Literal["error", "warning"]
    code: str
    message: str
    field: ImportField | None = None


class ImportPreviewRow(DomainModel):
    source_row_number: int = Field(ge=1)
    source_row_hash: str
    symbol_raw: str
    contract_code: str | None = None
    side: Literal["buy", "sell"] | None = None
    quantity: DecimalStr | None = None
    price: DecimalStr | None = None
    fees: DecimalStr | None = None
    currency: str | None = None
    fill_time: UtcDatetime | None = None
    fill_tz: str | None = None
    venue: str | None = None
    instrument_id: UUID | None = None
    instrument_symbol: str | None = None
    asset_class: str | None = None
    multiplier: DecimalStr | None = None
    is_complete: bool = False
    is_duplicate: bool = False
    issues: tuple[ImportRowIssue, ...] = ()


class ImportPreview(DomainModel):
    filename: str
    mapping: CsvColumnMapping
    rows: tuple[ImportPreviewRow, ...]
    row_count: int
    complete_count: int
    incomplete_count: int
    duplicate_count: int
    error_count: int
    trusted_row_count: int = Field(
        description="Rows that would be imported and count toward trusted P&L totals."
    )


class ImportCommitResult(DomainModel):
    batch_id: UUID
    imported_count: int
    duplicate_count: int
    skipped_incomplete: int
    error_count: int


class ImportedFillView(DomainModel):
    id: UUID
    batch_id: UUID
    source_row_number: int
    source_row_hash: str
    symbol_raw: str
    contract_code: str | None = None
    side: Literal["buy", "sell"]
    quantity: DecimalStr
    price: DecimalStr
    fees: DecimalStr
    currency: str
    fill_time: UtcDatetime
    fill_tz: str
    venue: str | None = None
    instrument_id: UUID | None = None
    instrument_symbol: str | None = None
    asset_class: str | None = None
    multiplier: DecimalStr | None = None
    is_complete: bool
    notes: str | None = None
    source_row_raw: dict[str, str] | None = None


class RealizedPnLLine(DomainModel):
    instrument_id: UUID | None
    symbol: str
    asset_class: str | None = None
    contract_code: str | None = None
    currency: str
    realized_pnl: DecimalStr
    fees: DecimalStr
    net_pnl: DecimalStr
    fill_count: int
    incomplete_fill_count: int = 0


class TradingSummary(DomainModel):
    """Realized P&L from imported fills. No portfolio return without balances and cash flows."""

    lines: tuple[RealizedPnLLine, ...]
    total_realized_pnl: DecimalStr
    total_fees: DecimalStr
    total_net_pnl: DecimalStr
    trusted_fill_count: int
    incomplete_fill_count: int
    has_account_snapshots: bool = False
    portfolio_return_available: bool = False


class KalshiMarket(DomainModel):
    ticker: str
    title: str
    category: str
    status: str
    yes_bid: DecimalStr | None = None
    yes_ask: DecimalStr | None = None
    no_bid: DecimalStr | None = None
    no_ask: DecimalStr | None = None
    last_price: DecimalStr | None = None
    volume: int | None = None
    close_time: UtcDatetime | None = None
    provenance: Provenance


class KalshiSourceRef(DomainModel):
    label: str
    url: str
    retrieved_at: UtcDatetime


class KalshiEventBrief(DomainModel):
    ticker: str
    title: str
    event_summary: str
    settlement_rules: str
    yes_scenario: str
    no_scenario: str
    fee_notes: str
    sources: tuple[KalshiSourceRef, ...]
    provenance: Provenance
    is_demonstration: bool = Field(
        default=False,
        description="True when served from fixtures or when live Kalshi is unavailable.",
    )
