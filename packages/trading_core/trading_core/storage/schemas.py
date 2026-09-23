"""Arrow schemas for bars and trades plus conversions to/from domain models.

Prices and sizes are ``decimal128`` in Parquet so no float rounding ever enters the pipeline.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import pyarrow as pa

from trading_core.domain.market import Bar, Trade

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

PRICE_TYPE = pa.decimal128(20, 8)
SIZE_TYPE = pa.decimal128(24, 8)
TIMESTAMP_TYPE = pa.timestamp("us", tz="UTC")

_BAR_FIELDS: list[pa.Field[Any]] = [
    pa.field("instrument_id", pa.string(), nullable=False),
    pa.field("contract_code", pa.string(), nullable=True),
    pa.field("timeframe", pa.string(), nullable=False),
    pa.field("origin_time", TIMESTAMP_TYPE, nullable=False),
    pa.field("origin_tz", pa.string(), nullable=False),
    pa.field("open", PRICE_TYPE, nullable=False),
    pa.field("high", PRICE_TYPE, nullable=False),
    pa.field("low", PRICE_TYPE, nullable=False),
    pa.field("close", PRICE_TYPE, nullable=False),
    pa.field("volume", SIZE_TYPE, nullable=False),
    pa.field("trade_count", pa.int64(), nullable=True),
    pa.field("vwap", PRICE_TYPE, nullable=True),
    pa.field("is_complete", pa.bool_(), nullable=False),
    pa.field("data_revision", pa.string(), nullable=False),
    pa.field("provenance", pa.string(), nullable=False),
]
BARS_SCHEMA = pa.schema(_BAR_FIELDS)

_TRADE_FIELDS: list[pa.Field[Any]] = [
    pa.field("instrument_id", pa.string(), nullable=False),
    pa.field("contract_code", pa.string(), nullable=True),
    pa.field("sequence", pa.int64(), nullable=False),
    pa.field("trade_time", TIMESTAMP_TYPE, nullable=False),
    pa.field("trade_tz", pa.string(), nullable=False),
    pa.field("price", PRICE_TYPE, nullable=False),
    pa.field("size", SIZE_TYPE, nullable=False),
    pa.field("side", pa.string(), nullable=False),
    pa.field("venue", pa.string(), nullable=False),
    pa.field("data_revision", pa.string(), nullable=False),
    pa.field("provenance", pa.string(), nullable=False),
]
TRADES_SCHEMA = pa.schema(_TRADE_FIELDS)


def bars_to_table(bars: Sequence[Bar]) -> pa.Table:
    rows = [
        {**bar.model_dump(mode="python"), "instrument_id": str(bar.instrument_id)} for bar in bars
    ]
    return pa.Table.from_pylist(rows, schema=BARS_SCHEMA)


def table_to_bars(table: pa.Table) -> list[Bar]:
    return [Bar.model_validate(row) for row in _rows(table, BARS_SCHEMA)]


def trades_to_table(trades: Sequence[Trade]) -> pa.Table:
    rows = [
        {**trade.model_dump(mode="python"), "instrument_id": str(trade.instrument_id)}
        for trade in trades
    ]
    return pa.Table.from_pylist(rows, schema=TRADES_SCHEMA)


def table_to_trades(table: pa.Table) -> list[Trade]:
    return [Trade.model_validate(row) for row in _rows(table, TRADES_SCHEMA)]


def _rows(table: pa.Table, schema: pa.Schema) -> Iterable[dict[str, object]]:
    if table.schema.names != schema.names:
        msg = f"unexpected columns {table.schema.names}; expected {schema.names}"
        raise ValueError(msg)
    for row in table.to_pylist():
        yield {**row, "instrument_id": UUID(cast("str", row["instrument_id"]))}


def _canonical(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return ""
    return str(value)


def content_hash(table: pa.Table) -> str:
    """SHA-256 over a canonical text encoding of every row; independent of the Arrow version."""
    digest = hashlib.sha256()
    digest.update("\x1f".join(table.schema.names).encode())
    digest.update(b"\n")
    for row in table.to_pylist():
        digest.update("\x1f".join(_canonical(row[name]) for name in table.schema.names).encode())
        digest.update(b"\n")
    return digest.hexdigest()
