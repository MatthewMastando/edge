"""Unit tests for mapping-driven CSV import."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from trading_core.domain.trading_records import CsvColumnMapping, ImportedFillView
from trading_core.imports.csv import build_import_preview
from trading_core.imports.pnl import (
    InstrumentLookup,
    ResolvedInstrument,
    SettlementCash,
    compute_trading_summary,
)

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


def test_duplicate_detection_uses_source_row_not_economics() -> None:
    first = build_import_preview(
        filename="sample.csv",
        csv_text=SAMPLE,
        mapping=_mapping(),
        lookup=_lookup(),
        existing_hashes=set(),
    )
    first_hash = first.rows[0].source_row_hash
    shifted = _mapping().model_copy(update={"default_fill_tz": "America/Chicago"})
    same_file = build_import_preview(
        filename="sample.csv",
        csv_text=SAMPLE,
        mapping=shifted,
        lookup=_lookup(),
        existing_hashes={first_hash},
    )
    assert same_file.rows[0].source_row_hash == first_hash
    assert same_file.duplicate_count == 1

    distinct = """Symbol,Side,Quantity,Price,Date,Fees,Contract,OrderId
6E,buy,1,1.0850,2025-09-10 14:30:00,1.25,6EZ6,A
6E,buy,1,1.0850,2025-09-10 14:30:00,1.25,6EZ6,B
"""
    mapping = _mapping().model_copy(update={"columns": {**_mapping().columns, "venue": "OrderId"}})
    preview = build_import_preview(
        filename="orders.csv",
        csv_text=distinct,
        mapping=mapping,
        lookup=_lookup(),
        existing_hashes=set(),
    )
    assert preview.duplicate_count == 0
    assert preview.trusted_row_count == 2
    assert preview.rows[0].source_row_hash != preview.rows[1].source_row_hash


def test_unknown_instrument_is_flagged_and_not_trusted() -> None:
    text = """Symbol,Side,Quantity,Price,Date,Fees,Contract
UNKNOWN,buy,1,10,2025-09-12 16:00:00,0,
"""
    preview = build_import_preview(
        filename="unknown.csv",
        csv_text=text,
        mapping=_mapping(),
        lookup=_lookup(),
        existing_hashes=set(),
    )
    row = preview.rows[0]
    assert row.will_import is True
    assert row.is_complete is False
    assert preview.trusted_row_count == 0
    assert preview.incomplete_count == 1
    assert any(issue.code == "unknown_instrument" for issue in row.issues)


def test_negative_futures_price_is_accepted() -> None:
    text = """Symbol,Side,Quantity,Price,Date,Fees,Contract
6E,buy,1,-0.25,2025-09-10 14:30:00,1.25,6EZ6
"""
    preview = build_import_preview(
        filename="negative.csv",
        csv_text=text,
        mapping=_mapping(),
        lookup=_lookup(),
        existing_hashes=set(),
    )
    assert preview.rows[0].is_complete is True
    assert preview.rows[0].price == Decimal("-0.25")


def test_settlement_cash_is_not_a_trusted_fill() -> None:
    text = """Symbol,Side,Quantity,Price,Date,Fees,Contract,Activity,Cash
6E,buy,1,1.0850,2025-09-10 14:30:00,1.25,6EZ6,trade,
6E,sell,1,1.0865,2025-09-11 10:00:00,1.25,6EZ6,trade,
6E,,,,2025-09-11 16:00:00,0,6EZ6,settlement,187.50
"""
    mapping = _mapping().model_copy(
        update={"columns": {**_mapping().columns, "activity": "Activity", "cash_amount": "Cash"}}
    )
    preview = build_import_preview(
        filename="settlement.csv",
        csv_text=text,
        mapping=mapping,
        lookup=_lookup(),
        existing_hashes=set(),
    )
    assert preview.trusted_row_count == 2
    assert preview.settlement_count == 1
    assert preview.importable_count == 3
    settlement = preview.rows[2]
    assert settlement.row_kind == "settlement"
    assert settlement.cash_amount == Decimal("187.50")
    assert any(issue.code == "settlement_excluded" for issue in settlement.issues)


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
    # (1.0865 - 1.0850) * 1 * 125000 = 187.5 realized before fees.
    # Fees stay in currency; they are not scaled by the contract multiplier.
    assert summary.total_realized_pnl == Decimal("187.5")
    assert summary.total_fees == Decimal("2.50")
    assert summary.total_net_pnl == Decimal("185.00")
    assert summary.portfolio_return_available is False
    assert summary.summary_currency == "USD"

    doubled = compute_trading_summary(
        fills,
        has_account_snapshots=True,
        settlements=[
            SettlementCash(
                instrument_id=inst_id,
                symbol="6E",
                contract_code="6EZ6",
                currency="USD",
                amount=Decimal("187.5"),
            )
        ],
    )
    assert doubled.total_realized_pnl == Decimal("187.5")
    assert doubled.settlement_cash_excluded == Decimal("187.5")
    assert doubled.settlement_flow_count == 1
    assert doubled.portfolio_return_available is False


def _fill(
    *,
    instrument_id: UUID,
    contract_code: str,
    side: Literal["buy", "sell"],
    price: Decimal,
    fill_time: datetime,
    source_row_hash: str,
    source_row_number: int,
) -> ImportedFillView:
    return ImportedFillView(
        id=uuid4(),
        batch_id=uuid4(),
        source_row_number=source_row_number,
        source_row_hash=source_row_hash,
        symbol_raw="6E",
        contract_code=contract_code,
        side=side,
        quantity=Decimal(1),
        price=price,
        fees=Decimal(0),
        currency="USD",
        fill_time=fill_time,
        fill_tz="America/New_York",
        instrument_id=instrument_id,
        instrument_symbol="6E",
        asset_class="futures",
        multiplier=Decimal(125000),
        is_complete=True,
    )


def test_fifo_does_not_cross_different_contracts() -> None:
    inst_id = uuid4()
    opened = _fill(
        instrument_id=inst_id,
        contract_code="6EZ6",
        side="buy",
        price=Decimal("1.0850"),
        fill_time=datetime(2025, 9, 10, 14, 30, tzinfo=UTC),
        source_row_hash="z-buy",
        source_row_number=2,
    )
    closed = _fill(
        instrument_id=inst_id,
        contract_code="6EH7",
        side="sell",
        price=Decimal("1.0900"),
        fill_time=datetime(2025, 9, 11, 10, 0, tzinfo=UTC),
        source_row_hash="h-sell",
        source_row_number=3,
    )
    summary = compute_trading_summary([opened, closed], has_account_snapshots=False)
    assert summary.total_realized_pnl == Decimal(0)
    assert len(summary.lines) == 2


def test_incomplete_fills_are_excluded_from_trusted_totals() -> None:
    inst_id = uuid4()
    trusted = ImportedFillView(
        id=uuid4(),
        batch_id=uuid4(),
        source_row_number=2,
        source_row_hash="ok",
        symbol_raw="6E",
        contract_code="6EZ6",
        side="buy",
        quantity=Decimal(1),
        price=Decimal("1.00"),
        fees=Decimal("1"),
        currency="USD",
        fill_time=datetime(2025, 9, 10, tzinfo=UTC),
        fill_tz="UTC",
        instrument_id=inst_id,
        multiplier=Decimal(125000),
        is_complete=True,
    )
    flagged = trusted.model_copy(
        update={
            "id": uuid4(),
            "source_row_hash": "bad",
            "source_row_number": 3,
            "symbol_raw": "UNKNOWN",
            "instrument_id": None,
            "is_complete": False,
            "fees": Decimal("99"),
        }
    )
    summary = compute_trading_summary([trusted, flagged], has_account_snapshots=False)
    assert summary.trusted_fill_count == 1
    assert summary.incomplete_fill_count == 1
    assert summary.total_fees == Decimal(1)
