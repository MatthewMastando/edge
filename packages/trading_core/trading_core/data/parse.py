"""Shared parsers for live market payloads. Missing numbers stay missing."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from trading_core.labeling import SourceFailure

PRICE_SCALE = Decimal("1000000000")
_MONTHS = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}


def revision_id(provider: str, body: bytes, *, recorded: bool) -> str:
    digest = hashlib.sha256(body).hexdigest()[:16]
    prefix = "recorded" if recorded else "live"
    return f"{prefix}-{provider}-{digest}"


def parse_decimal(raw: object, *, source: str, field: str) -> Decimal:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        raise SourceFailure(
            source=source,
            coverage=f"{field} was absent",
            delay="not applicable",
            reason=f"{field} was missing and was not invented",
            status="missing_coverage",
        )
    try:
        return Decimal(str(raw))
    except InvalidOperation as exc:
        raise SourceFailure(
            source=source,
            coverage=f"{field} was not a decimal",
            delay="not applicable",
            reason=f"{field} could not be parsed",
        ) from exc


def fixed_price(raw: object, *, source: str) -> Decimal:
    """Databento CSV prices are 1e-9 fixed-point integers."""
    return parse_decimal(raw, source=source, field="price") / PRICE_SCALE


def json_object(body: bytes, *, source: str) -> dict[str, object]:
    try:
        parsed: object = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SourceFailure(
            source=source,
            coverage="response was not JSON",
            delay="not applicable",
            reason="response body was not JSON",
        ) from exc
    if not isinstance(parsed, dict):
        raise SourceFailure(
            source=source,
            coverage="response was not a JSON object",
            delay="not applicable",
            reason="response JSON was not an object",
        )
    return cast("dict[str, object]", parsed)


def json_list(body: bytes, *, source: str) -> list[object]:
    try:
        parsed: object = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SourceFailure(
            source=source,
            coverage="response was not JSON",
            delay="not applicable",
            reason="response body was not JSON",
        ) from exc
    if not isinstance(parsed, list):
        raise SourceFailure(
            source=source,
            coverage="response was not a JSON array",
            delay="not applicable",
            reason="response JSON was not an array",
        )
    return list(parsed)


def csv_rows(body: bytes, *, source: str) -> list[dict[str, str]]:
    text = body.decode("utf-8-sig", errors="replace")
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    if not lines:
        return []
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    if reader.fieldnames is None:
        raise SourceFailure(
            source=source,
            coverage="CSV had no header",
            delay="not applicable",
            reason="CSV response had no header",
        )
    return [dict(row) for row in reader]


def ns_to_datetime(raw: str, *, source: str) -> datetime:
    value = parse_decimal(raw, source=source, field="timestamp")
    seconds = int(value) / 1_000_000_000
    return datetime.fromtimestamp(seconds, tz=UTC)


def unix_seconds(raw: object, *, source: str) -> datetime:
    value = parse_decimal(raw, source=source, field="timestamp")
    return datetime.fromtimestamp(int(value), tz=UTC)


def iso_datetime(raw: str) -> datetime:
    text = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def futures_contract_parts(symbol: str) -> tuple[str, str] | None:
    """Split a listed code such as ESZ6 or 6EZ6. Continuous symbols are not contracts."""
    if len(symbol) < 3 or any(mark in symbol for mark in (".", "!", " ")):
        return None
    year = symbol[-1]
    month = symbol[-2]
    root = symbol[:-2]
    if year.isdigit() and month in _MONTHS and root.isalnum():
        return root, symbol
    return None


def is_continuous_symbol(symbol: str) -> bool:
    upper = symbol.upper()
    return "!" in symbol or upper.endswith(".C.0") or ".C." in upper or upper.endswith(".CONT")
