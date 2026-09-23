"""Parse, validate, and persist CSV fills with duplicate detection."""

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

_REQUIRED: tuple[str, ...] = ("symbol", "side", "quantity", "price", "fill_time")


def _normalize_side(raw: str) -> Literal["buy", "sell"] | None:
    value = raw.strip().lower()
    if value in {"buy", "b", "bot", "purchase"}:
        return "buy"
    if value in {"sell", "s", "sold", "sale"}:
        return "sell"
    return None


def _parse_decimal(raw: str) -> Decimal | None:
    cleaned = raw.strip().replace(",", "").replace("$", "")
    if not cleaned:
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


def _row_hash(
    *,
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
    fill_time: datetime,
    fees: Decimal,
    contract_code: str | None,
) -> str:
    payload = "|".join(
        [
            symbol.strip().upper(),
            side,
            format(quantity, "f"),
            format(price, "f"),
            fill_time.isoformat(),
            format(fees, "f"),
            (contract_code or "").strip().upper(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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

    if not symbol_raw:
        issues.append(
            ImportRowIssue(
                source_row_number=row_number,
                severity="error",
                code="missing_symbol",
                message="Symbol is required.",
                field="symbol",
            )
        )

    side = _normalize_side(side_raw) if side_raw else None
    if side is None:
        issues.append(
            ImportRowIssue(
                source_row_number=row_number,
                severity="error",
                code="invalid_side",
                message="Side must be buy or sell.",
                field="side",
            )
        )

    quantity = _parse_decimal(qty_raw) if qty_raw else None
    if quantity is None or quantity <= 0:
        issues.append(
            ImportRowIssue(
                source_row_number=row_number,
                severity="error",
                code="invalid_quantity",
                message="Quantity must be a positive number.",
                field="quantity",
            )
        )

    price = _parse_decimal(price_raw) if price_raw else None
    if price is None or price <= 0:
        issues.append(
            ImportRowIssue(
                source_row_number=row_number,
                severity="error",
                code="invalid_price",
                message="Price must be a positive number.",
                field="price",
            )
        )

    fees = _parse_decimal(fees_raw) if fees_raw else Decimal(0)
    if fees is None or fees < 0:
        issues.append(
            ImportRowIssue(
                source_row_number=row_number,
                severity="error",
                code="invalid_fees",
                message="Fees must be zero or positive.",
                field="fees",
            )
        )
        fees = Decimal(0)

    fill_time = _parse_time(time_raw, fill_tz) if time_raw else None
    if fill_time is None:
        issues.append(
            ImportRowIssue(
                source_row_number=row_number,
                severity="error",
                code="invalid_fill_time",
                message="Fill time could not be parsed.",
                field="fill_time",
            )
        )

    instrument_id: UUID | None = None
    instrument_symbol: str | None = None
    asset_class: str | None = None
    multiplier: Decimal | None = None
    if symbol_raw:
        resolved = lookup.resolve(symbol_raw, contract_code)
        if resolved is None:
            issues.append(
                ImportRowIssue(
                    source_row_number=row_number,
                    severity="warning",
                    code="unknown_instrument",
                    message="Unknown instrument; row excluded from trusted totals.",
                    field="symbol",
                )
            )
        else:
            instrument_id = resolved.instrument_id
            instrument_symbol = resolved.symbol
            asset_class = resolved.asset_class
            multiplier = resolved.multiplier

    row_hash = ""
    is_duplicate = False
    if (
        side is not None
        and quantity is not None
        and price is not None
        and fill_time is not None
        and symbol_raw
    ):
        row_hash = _row_hash(
            symbol=symbol_raw,
            side=side,
            quantity=quantity,
            price=price,
            fill_time=fill_time,
            fees=fees,
            contract_code=contract_code,
        )
        is_duplicate = row_hash in existing_hashes

    has_errors = any(issue.severity == "error" for issue in issues)
    is_complete = (
        not has_errors
        and instrument_id is not None
        and side is not None
        and quantity is not None
        and price is not None
        and fill_time is not None
    )

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
        is_complete=is_complete,
        is_duplicate=is_duplicate,
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
        if preview_row.source_row_hash and preview_row.source_row_hash in seen_hashes:
            preview_row = preview_row.model_copy(
                update={"is_duplicate": True, "is_complete": False}
            )
        elif preview_row.source_row_hash:
            seen_hashes.add(preview_row.source_row_hash)
        preview_rows.append(preview_row)

    complete = sum(1 for r in preview_rows if r.is_complete and not r.is_duplicate)
    incomplete = sum(1 for r in preview_rows if not r.is_complete)
    duplicates = sum(1 for r in preview_rows if r.is_duplicate)
    errors = sum(1 for r in preview_rows if any(i.severity == "error" for i in r.issues))
    trusted = complete

    return ImportPreview(
        filename=filename,
        mapping=mapping,
        rows=tuple(preview_rows),
        row_count=len(preview_rows),
        complete_count=complete,
        incomplete_count=incomplete,
        duplicate_count=duplicates,
        error_count=errors,
        trusted_row_count=trusted,
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
    errors = 0

    _headers, raw_rows = _read_csv(csv_text)
    raw_by_number = {index + 2: row for index, row in enumerate(raw_rows)}

    seen_this_batch: set[str] = set()

    for row in preview.rows:
        if row.is_duplicate or (row.source_row_hash and row.source_row_hash in seen_this_batch):
            duplicates += 1
            continue
        if not row.is_complete:
            skipped_incomplete += 1
            if any(issue.severity == "error" for issue in row.issues):
                errors += 1
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

        raw = raw_by_number.get(row.source_row_number, {})
        await analytics.insert_fill(
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
            is_complete=True,
            source_row_raw=raw,
        )
        if row.source_row_hash:
            imported += 1
            existing_hashes.add(row.source_row_hash)
            seen_this_batch.add(row.source_row_hash)

    await analytics.finalize_import_batch(
        conn,
        batch_id=batch_id,
        row_count=preview.row_count,
        imported_count=imported,
        duplicate_count=duplicates,
        error_count=errors + skipped_incomplete,
        status="imported",
    )

    return ImportCommitResult(
        batch_id=batch_id,
        imported_count=imported,
        duplicate_count=duplicates,
        skipped_incomplete=skipped_incomplete,
        error_count=errors,
    )
