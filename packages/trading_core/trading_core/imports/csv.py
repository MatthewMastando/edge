"""Parse, validate, and persist CSV fills with source-row duplicate detection."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trading_core.domain.trading_records import (
    CsvColumnMapping,
    ImportCommitResult,
    ImportField,
    ImportPreview,
    ImportPreviewRow,
    ImportRowIssue,
)
from trading_core.imports.pnl import InstrumentLookup  # noqa: TC001
from trading_core.storage.repositories import analytics

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection

_SETTLEMENT_RE = re.compile(
    r"\b(settlement|variation margin|mark[- ]to[- ]market|mtm)\b",
    re.IGNORECASE,
)


def _normalize_side(raw: str) -> Literal["buy", "sell"] | None:
    value = raw.strip().lower()
    if value in {"buy", "b", "bot", "purchase"}:
        return "buy"
    if value in {"sell", "s", "sold", "sale"}:
        return "sell"
    return None


def _parse_decimal(raw: str) -> Decimal | None:
    cleaned = raw.strip().replace(",", "").replace("$", "").replace("(", "-").replace(")", "")
    if not cleaned or cleaned == "-":
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_time(raw: str, tz_name: str) -> datetime | None:
    text = raw.strip()
    if not text:
        return None
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt)  # noqa: DTZ007 — tz applied below
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=zone)
            return parsed.astimezone(UTC)
        except ValueError:
            continue
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=zone)
            return parsed.astimezone(UTC)
        except ValueError:
            return None
    return None


def source_row_hash(row: dict[str, str]) -> str:
    """Identity of the source row, not of the mapped economics.

    Reimporting the same cells skips the row even if the timezone preset changes.
    Two rows that share price and size but differ in any cell (an order id, for
    example) stay distinct.
    """
    payload = "\n".join(f"{key}={row[key]}" for key in sorted(row))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_settlement(activity: str, side_raw: str) -> bool:
    return _SETTLEMENT_RE.search(f"{activity} {side_raw}") is not None


def _read_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return [], []
    headers = [h.strip() for h in reader.fieldnames]
    rows: list[dict[str, str]] = []
    for row in reader:
        normalized = {k.strip(): (v or "").strip() for k, v in row.items() if k is not None}
        if any(normalized.values()):
            rows.append(normalized)
    return headers, rows


def _cell(row: dict[str, str], mapping: CsvColumnMapping, field: ImportField) -> str:
    header = mapping.columns.get(field)
    if header is None:
        return ""
    return row.get(header, "").strip()


def _issue(
    row_number: int,
    *,
    severity: Literal["error", "warning"],
    code: str,
    message: str,
    field: ImportField | None = None,
) -> ImportRowIssue:
    return ImportRowIssue(
        source_row_number=row_number,
        severity=severity,
        code=code,
        message=message,
        field=field,
    )


def _preview_row(
    *,
    row_number: int,
    row: dict[str, str],
    mapping: CsvColumnMapping,
    lookup: InstrumentLookup,
    existing_hashes: set[str],
) -> ImportPreviewRow:
    issues: list[ImportRowIssue] = []
    symbol_raw = _cell(row, mapping, "symbol")
    side_raw = _cell(row, mapping, "side")
    qty_raw = _cell(row, mapping, "quantity")
    price_raw = _cell(row, mapping, "price")
    fees_raw = _cell(row, mapping, "fees")
    time_raw = _cell(row, mapping, "fill_time")
    currency_raw = _cell(row, mapping, "currency") or mapping.default_currency
    contract_code = _cell(row, mapping, "contract_code") or None
    venue = _cell(row, mapping, "venue") or None
    fill_tz = _cell(row, mapping, "fill_tz") or mapping.default_fill_tz
    activity = _cell(row, mapping, "activity")
    cash_raw = _cell(row, mapping, "cash_amount")
    row_hash = source_row_hash(row)
    is_duplicate = row_hash in existing_hashes
    settlement = _is_settlement(activity, side_raw)

    if not symbol_raw:
        issues.append(
            _issue(
                row_number,
                severity="error",
                code="missing_symbol",
                message="Symbol is required.",
                field="symbol",
            )
        )

    fill_time = _parse_time(time_raw, fill_tz) if time_raw else None
    if fill_time is None:
        issues.append(
            _issue(
                row_number,
                severity="error",
                code="invalid_fill_time",
                message="Fill time could not be parsed.",
                field="fill_time",
            )
        )

    instrument_id = None
    instrument_symbol = None
    asset_class = None
    multiplier = None
    if symbol_raw:
        resolved = lookup.resolve(symbol_raw, contract_code)
        if resolved is None:
            issues.append(
                _issue(
                    row_number,
                    severity="warning",
                    code="unknown_instrument",
                    message="Unknown instrument; row is flagged and excluded from trusted totals.",
                    field="symbol",
                )
            )
        else:
            instrument_id = resolved.instrument_id
            instrument_symbol = resolved.symbol
            asset_class = resolved.asset_class
            multiplier = resolved.multiplier

    if settlement:
        return _settlement_preview(
            row_number=row_number,
            issues=issues,
            symbol_raw=symbol_raw,
            contract_code=contract_code,
            currency_raw=currency_raw,
            fill_time=fill_time,
            fill_tz=fill_tz,
            venue=venue,
            instrument_id=instrument_id,
            instrument_symbol=instrument_symbol,
            asset_class=asset_class,
            multiplier=multiplier,
            cash_raw=cash_raw,
            row_hash=row_hash,
            is_duplicate=is_duplicate,
        )

    return _fill_preview(
        row_number=row_number,
        issues=issues,
        symbol_raw=symbol_raw,
        side_raw=side_raw,
        qty_raw=qty_raw,
        price_raw=price_raw,
        fees_raw=fees_raw,
        contract_code=contract_code,
        currency_raw=currency_raw,
        fill_time=fill_time,
        fill_tz=fill_tz,
        venue=venue,
        instrument_id=instrument_id,
        instrument_symbol=instrument_symbol,
        asset_class=asset_class,
        multiplier=multiplier,
        row_hash=row_hash,
        is_duplicate=is_duplicate,
    )


def _settlement_preview(
    *,
    row_number: int,
    issues: list[ImportRowIssue],
    symbol_raw: str,
    contract_code: str | None,
    currency_raw: str,
    fill_time: datetime | None,
    fill_tz: str,
    venue: str | None,
    instrument_id: UUID | None,
    instrument_symbol: str | None,
    asset_class: str | None,
    multiplier: Decimal | None,
    cash_raw: str,
    row_hash: str,
    is_duplicate: bool,
) -> ImportPreviewRow:
    cash_amount = _parse_decimal(cash_raw) if cash_raw else None
    if cash_amount is None:
        issues.append(
            _issue(
                row_number,
                severity="error",
                code="invalid_cash_amount",
                message="Settlement rows need a cash amount.",
                field="cash_amount",
            )
        )
    else:
        issues.append(
            _issue(
                row_number,
                severity="warning",
                code="settlement_excluded",
                message=(
                    "Settlement cash is stored for provenance and excluded from FIFO "
                    "realized P&L so it is not double-counted."
                ),
                field="cash_amount",
            )
        )
    has_errors = any(issue.severity == "error" for issue in issues)
    will_import = not has_errors and not is_duplicate and cash_amount is not None
    return ImportPreviewRow(
        source_row_number=row_number,
        source_row_hash=row_hash,
        symbol_raw=symbol_raw or "(missing)",
        contract_code=contract_code,
        side=None,
        quantity=None,
        price=None,
        fees=Decimal(0),
        cash_amount=cash_amount,
        currency=currency_raw,
        fill_time=fill_time,
        fill_tz=fill_tz,
        venue=venue,
        instrument_id=instrument_id,
        instrument_symbol=instrument_symbol,
        asset_class=asset_class,
        multiplier=multiplier,
        row_kind="settlement",
        is_complete=will_import or (not has_errors and is_duplicate),
        is_duplicate=is_duplicate,
        will_import=will_import,
        issues=tuple(issues),
    )


def _fill_preview(
    *,
    row_number: int,
    issues: list[ImportRowIssue],
    symbol_raw: str,
    side_raw: str,
    qty_raw: str,
    price_raw: str,
    fees_raw: str,
    contract_code: str | None,
    currency_raw: str,
    fill_time: datetime | None,
    fill_tz: str,
    venue: str | None,
    instrument_id: UUID | None,
    instrument_symbol: str | None,
    asset_class: str | None,
    multiplier: Decimal | None,
    row_hash: str,
    is_duplicate: bool,
) -> ImportPreviewRow:
    side = _normalize_side(side_raw) if side_raw else None
    if side is None:
        issues.append(
            _issue(
                row_number,
                severity="error",
                code="invalid_side",
                message="Side must be buy or sell.",
                field="side",
            )
        )

    quantity = _parse_decimal(qty_raw) if qty_raw else None
    if quantity is None or quantity <= 0:
        issues.append(
            _issue(
                row_number,
                severity="error",
                code="invalid_quantity",
                message="Quantity must be a positive number.",
                field="quantity",
            )
        )

    # Futures can print negative (for example, a commodity contract). Reject only
    # values that are not numbers.
    price = _parse_decimal(price_raw) if price_raw else None
    if price is None:
        issues.append(
            _issue(
                row_number,
                severity="error",
                code="invalid_price",
                message="Price must be a number.",
                field="price",
            )
        )

    fees = _parse_decimal(fees_raw) if fees_raw else Decimal(0)
    if fees is None or fees < 0:
        issues.append(
            _issue(
                row_number,
                severity="error",
                code="invalid_fees",
                message="Fees must be zero or positive.",
                field="fees",
            )
        )
        fees = Decimal(0)

    has_errors = any(issue.severity == "error" for issue in issues)
    economics_ok = (
        not has_errors
        and side is not None
        and quantity is not None
        and price is not None
        and fill_time is not None
        and bool(symbol_raw)
    )
    is_complete = economics_ok and instrument_id is not None
    will_import = economics_ok and not is_duplicate

    return ImportPreviewRow(
        source_row_number=row_number,
        source_row_hash=row_hash,
        symbol_raw=symbol_raw or "(missing)",
        contract_code=contract_code,
        side=side,
        quantity=quantity,
        price=price,
        fees=fees,
        currency=currency_raw,
        fill_time=fill_time,
        fill_tz=fill_tz,
        venue=venue,
        instrument_id=instrument_id,
        instrument_symbol=instrument_symbol,
        asset_class=asset_class,
        multiplier=multiplier,
        row_kind="fill",
        is_complete=is_complete,
        is_duplicate=is_duplicate,
        will_import=will_import,
        issues=tuple(issues),
    )


def build_import_preview(
    *,
    filename: str,
    csv_text: str,
    mapping: CsvColumnMapping,
    lookup: InstrumentLookup,
    existing_hashes: set[str],
) -> ImportPreview:
    _headers, rows = _read_csv(csv_text)
    preview_rows: list[ImportPreviewRow] = []
    seen_hashes: set[str] = set(existing_hashes)
    for index, row in enumerate(rows, start=2):
        preview_row = _preview_row(
            row_number=index,
            row=row,
            mapping=mapping,
            lookup=lookup,
            existing_hashes=seen_hashes,
        )
        if (
            preview_row.will_import
            and preview_row.source_row_hash
            and preview_row.source_row_hash not in seen_hashes
        ):
            seen_hashes.add(preview_row.source_row_hash)
        preview_rows.append(preview_row)

    complete = sum(
        1
        for row in preview_rows
        if row.row_kind == "fill" and row.is_complete and not row.is_duplicate
    )
    incomplete = sum(
        1
        for row in preview_rows
        if row.row_kind == "fill" and not row.is_complete and not row.is_duplicate
    )
    duplicates = sum(1 for row in preview_rows if row.is_duplicate)
    errors = sum(
        1 for row in preview_rows if any(issue.severity == "error" for issue in row.issues)
    )
    settlements = sum(1 for row in preview_rows if row.row_kind == "settlement" and row.will_import)
    importable = sum(1 for row in preview_rows if row.will_import)

    return ImportPreview(
        filename=filename,
        mapping=mapping,
        rows=tuple(preview_rows),
        row_count=len(preview_rows),
        complete_count=complete,
        incomplete_count=incomplete,
        duplicate_count=duplicates,
        error_count=errors,
        settlement_count=settlements,
        importable_count=importable,
        trusted_row_count=complete,
    )


async def commit_import(
    conn: AsyncConnection,
    *,
    owner_id: UUID,
    filename: str,
    mapping: CsvColumnMapping,
    csv_text: str,
    lookup: InstrumentLookup,
    existing_hashes: set[str],
) -> ImportCommitResult:
    preview = build_import_preview(
        filename=filename,
        csv_text=csv_text,
        mapping=mapping,
        lookup=lookup,
        existing_hashes=existing_hashes,
    )
    batch_id = await analytics.insert_import_batch(
        conn,
        owner_id=owner_id,
        filename=filename,
        mapping_preset=mapping.model_dump(mode="json"),
    )

    imported = 0
    duplicates = 0
    skipped_incomplete = 0
    incomplete_stored = 0
    settlement_stored = 0
    errors = 0

    _headers, raw_rows = _read_csv(csv_text)
    raw_by_number = {index + 2: row for index, row in enumerate(raw_rows)}

    for row in preview.rows:
        if any(issue.severity == "error" for issue in row.issues):
            errors += 1
        if row.is_duplicate:
            duplicates += 1
            continue
        if not row.will_import:
            skipped_incomplete += 1
            continue

        raw = raw_by_number.get(row.source_row_number, {})
        if row.row_kind == "settlement":
            if row.cash_amount is None or row.fill_time is None:
                skipped_incomplete += 1
                continue
            inserted = await analytics.insert_cash_flow(
                conn,
                batch_id=batch_id,
                source_row_number=row.source_row_number,
                source_row_hash=row.source_row_hash,
                symbol_raw=row.symbol_raw,
                currency=row.currency or mapping.default_currency,
                amount=row.cash_amount,
                flow_time=row.fill_time,
                flow_tz=row.fill_tz or mapping.default_fill_tz,
                instrument_id=row.instrument_id,
                contract_code=row.contract_code,
                source_row_raw=raw,
            )
            if inserted is None:
                duplicates += 1
                continue
            settlement_stored += 1
            continue

        if (
            row.side is None
            or row.quantity is None
            or row.price is None
            or row.fill_time is None
            or row.fees is None
            or row.currency is None
            or not row.source_row_hash
        ):
            skipped_incomplete += 1
            continue

        inserted_fill = await analytics.insert_fill(
            conn,
            batch_id=batch_id,
            source_row_number=row.source_row_number,
            source_row_hash=row.source_row_hash,
            symbol_raw=row.symbol_raw,
            side=row.side,
            quantity=row.quantity,
            price=row.price,
            currency=row.currency,
            fill_time=row.fill_time,
            fill_tz=row.fill_tz or mapping.default_fill_tz,
            instrument_id=row.instrument_id,
            contract_code=row.contract_code,
            fees=row.fees,
            venue=row.venue,
            multiplier=row.multiplier,
            is_complete=row.is_complete,
            source_row_raw=raw,
        )
        if inserted_fill is None:
            duplicates += 1
            continue
        if row.is_complete:
            imported += 1
        else:
            incomplete_stored += 1

    await analytics.finalize_import_batch(
        conn,
        batch_id=batch_id,
        row_count=preview.row_count,
        imported_count=imported,
        duplicate_count=duplicates,
        error_count=errors,
        status="imported",
    )

    return ImportCommitResult(
        batch_id=batch_id,
        imported_count=imported,
        duplicate_count=duplicates,
        skipped_incomplete=skipped_incomplete,
        incomplete_stored=incomplete_stored,
        settlement_stored=settlement_stored,
        error_count=errors,
    )
