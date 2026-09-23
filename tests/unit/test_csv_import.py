"""Unit tests for mapping-driven CSV import."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from trading_core.domain.trading_records import CsvColumnMapping, ImportedFillView
from trading_core.imports.csv import build_import_preview
from trading_core.imports.pnl import InstrumentLookup, ResolvedInstrument, compute_trading_summary

SAMPLE = """Symbol,Side,Quantity,Price,Date,Fees,Contract
6E,buy,2,1.0850,2025-09-10 14:30:00,1.25,6EZ6
6E,sell,1,1.0865,2025-09-11 10:00:00,1.25,6EZ6
"""


def _mapping() -> CsvColumnMapping:
    return CsvColumnMapping(
        columns={
            "symbol": "Symbol",
            "side": "Side",
            "quantity": "Quantity",
            "price": "Price",
            "fill_time": "Date",
            "fees": "Fees",
            "contract_code": "Contract",
        }
    )


def _lookup() -> InstrumentLookup:
    inst = ResolvedInstrument(
        instrument_id=uuid4(),
        symbol="6E",
        asset_class="fx_futures",
        multiplier=Decimal(125000),
    )
    return InstrumentLookup([inst], {"6EZ6": inst})


def test_preview_marks_complete_rows() -> None:
    preview = build_import_preview(
        filename="sample.csv",
        csv_text=SAMPLE,
        mapping=_mapping(),
        lookup=_lookup(),
        existing_hashes=set(),
    )
    assert preview.row_count == 2
    assert preview.complete_count == 2
    assert preview.trusted_row_count == 2
    assert all(row.is_complete for row in preview.rows)


def test_duplicate_detection() -> None:
    first = build_import_preview(
        filename="sample.csv",
        csv_text=SAMPLE,
        mapping=_mapping(),
        lookup=_lookup(),
        existing_hashes=set(),
    )
    first_hash = first.rows[0].source_row_hash
    preview2 = build_import_preview(
        filename="sample.csv",
        csv_text=SAMPLE,
        mapping=_mapping(),
        lookup=_lookup(),
        existing_hashes={first_hash},
    )
    assert preview2.duplicate_count == 1


def test_futures_realized_pnl_uses_multiplier() -> None:
    inst_id = uuid4()
    fills = [
        ImportedFillView(
            id=uuid4(),
            batch_id=uuid4(),
            source_row_number=2,
            source_row_hash="a",
            symbol_raw="6E",
            contract_code="6EZ6",
            side="buy",
            quantity=Decimal(2),
            price=Decimal("1.0850"),
            fees=Decimal("1.25"),
            currency="USD",
            fill_time=datetime(2025, 9, 10, 14, 30, tzinfo=UTC),
            fill_tz="America/New_York",
            instrument_id=inst_id,
            instrument_symbol="6E",
            asset_class="fx_futures",
            multiplier=Decimal(125000),
            is_complete=True,
        ),
        ImportedFillView(
            id=uuid4(),
            batch_id=uuid4(),
            source_row_number=3,
            source_row_hash="b",
            symbol_raw="6E",
            contract_code="6EZ6",
            side="sell",
            quantity=Decimal(1),
            price=Decimal("1.0865"),
            fees=Decimal("1.25"),
            currency="USD",
            fill_time=datetime(2025, 9, 11, 10, 0, tzinfo=UTC),
            fill_tz="America/New_York",
            instrument_id=inst_id,
            instrument_symbol="6E",
            asset_class="fx_futures",
            multiplier=Decimal(125000),
            is_complete=True,
        ),
    ]
    summary = compute_trading_summary(fills, has_account_snapshots=False)
    # (1.0865 - 1.0850) * 1 * 125000 = 187.5 realized before fees
    assert summary.total_realized_pnl == Decimal("187.5")
    assert summary.portfolio_return_available is False
