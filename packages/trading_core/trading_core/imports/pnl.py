"""Realized P&L from imported fills (FIFO, futures multipliers, fees)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003 — used in ResolvedInstrument at runtime

from trading_core.domain.trading_records import ImportedFillView, RealizedPnLLine, TradingSummary
from trading_core.storage.db import fetch_all
from trading_core.storage.repositories.common import (
    as_bool,
    as_datetime,
    as_decimal,
    as_str,
    as_uuid,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class ResolvedInstrument:
    instrument_id: UUID
    symbol: str
    asset_class: str
    multiplier: Decimal


class InstrumentLookup:
    """In-memory symbol resolution built from instruments and futures contracts."""

    def __init__(
        self,
        instruments: list[ResolvedInstrument],
        contract_by_code: dict[str, ResolvedInstrument],
    ) -> None:
        self._by_symbol = {item.symbol.upper(): item for item in instruments}
        self._contract_by_code = {k.upper(): v for k, v in contract_by_code.items()}

    def resolve(self, symbol_raw: str, contract_code: str | None) -> ResolvedInstrument | None:
        if contract_code:
            hit = self._contract_by_code.get(contract_code.strip().upper())
            if hit is not None:
                return hit
        return self._by_symbol.get(symbol_raw.strip().upper())

    @classmethod
    async def load(cls, conn: AsyncConnection) -> InstrumentLookup:
        instrument_rows = await fetch_all(
            conn,
            """
            select id, symbol, asset_class, multiplier
            from instruments
            """,
        )
        contract_rows = await fetch_all(
            conn,
            """
            select fc.contract_code, i.id, i.symbol, i.asset_class, fc.point_multiplier
            from futures_contracts fc
            join instruments i on i.id = fc.instrument_id
            """,
        )
        instruments = [
            ResolvedInstrument(
                instrument_id=as_uuid(row["id"]),
                symbol=as_str(row["symbol"]),
                asset_class=as_str(row["asset_class"]),
                multiplier=as_decimal(row["multiplier"]),
            )
            for row in instrument_rows
        ]
        contract_by_code = {
            as_str(row["contract_code"]): ResolvedInstrument(
                instrument_id=as_uuid(row["id"]),
                symbol=as_str(row["symbol"]),
                asset_class=as_str(row["asset_class"]),
                multiplier=as_decimal(row["point_multiplier"]),
            )
            for row in contract_rows
        }
        return cls(instruments, contract_by_code)


def _fill_view(row: dict[str, object]) -> ImportedFillView:
    raw = row.get("source_row_raw")
    source_row_raw: dict[str, str] | None = None
    if isinstance(raw, dict):
        source_row_raw = {str(k): str(v) for k, v in raw.items()}
    return ImportedFillView(
        id=as_uuid(row["id"]),
        batch_id=as_uuid(row["batch_id"]),
        source_row_number=int(as_decimal(row["source_row_number"])),
        source_row_hash=as_str(row["source_row_hash"]),
        symbol_raw=as_str(row["symbol_raw"]),
        contract_code=as_str(row["contract_code"]) if row.get("contract_code") else None,
        side=as_str(row["side"]),  # type: ignore[arg-type]
        quantity=as_decimal(row["quantity"]),
        price=as_decimal(row["price"]),
        fees=as_decimal(row["fees"]),
        currency=as_str(row["currency"]),
        fill_time=as_datetime(row["fill_time"]),
        fill_tz=as_str(row["fill_tz"]),
        venue=as_str(row["venue"]) if row.get("venue") else None,
        instrument_id=as_uuid(row["instrument_id"]) if row.get("instrument_id") else None,
        instrument_symbol=(
            as_str(row["instrument_symbol"]) if row.get("instrument_symbol") else None
        ),
        asset_class=as_str(row["asset_class"]) if row.get("asset_class") else None,
        multiplier=as_decimal(row["multiplier"]) if row.get("multiplier") is not None else None,
        is_complete=as_bool(row["is_complete"]),
        notes=as_str(row["notes"]) if row.get("notes") else None,
        source_row_raw=source_row_raw,
    )


async def list_fills_for_owner(
    conn: AsyncConnection,
    owner_id: UUID,
    *,
    asset_class: str | None = None,
    instrument_id: UUID | None = None,
    trusted_only: bool = False,
    limit: int = 500,
) -> list[ImportedFillView]:
    rows = await fetch_all(
        conn,
        """
        select f.*, i.symbol as instrument_symbol, i.asset_class
        from imported_fills f
        join import_batches b on b.id = f.batch_id
        left join instruments i on i.id = f.instrument_id
        where b.owner_id = :owner_id
          and (:asset_class is null or i.asset_class = :asset_class)
          and (:instrument_id is null or f.instrument_id = :instrument_id)
          and (not :trusted_only or f.is_complete = true)
        order by f.fill_time desc
        limit :limit
        """,
        {
            "owner_id": owner_id,
            "asset_class": asset_class,
            "instrument_id": instrument_id,
            "trusted_only": trusted_only,
            "limit": limit,
        },
    )
    return [_fill_view(row) for row in rows]


@dataclass
class _Lot:
    quantity: Decimal
    price: Decimal
    fees: Decimal


def _multiplier_for(fill: ImportedFillView) -> Decimal:
    if fill.multiplier is not None:
        return fill.multiplier
    return Decimal(1)


def _realized_for_group(fills: list[ImportedFillView]) -> tuple[Decimal, Decimal]:
    """FIFO realized P&L and fees for one instrument group."""
    ordered = sorted(fills, key=lambda f: f.fill_time)
    long_lots: list[_Lot] = []
    short_lots: list[_Lot] = []
    realized = Decimal(0)
    fees_total = Decimal(0)
    mult = _multiplier_for(ordered[0]) if ordered else Decimal(1)

    for fill in ordered:
        qty = fill.quantity
        price = fill.price
        fees = fill.fees
        fees_total += fees
        mult = _multiplier_for(fill)

        if fill.side == "buy":
            remaining = qty
            while remaining > 0 and short_lots:
                lot = short_lots[0]
                matched = min(remaining, lot.quantity)
                realized += (lot.price - price) * matched * mult
                lot.quantity -= matched
                remaining -= matched
                if lot.quantity <= 0:
                    short_lots.pop(0)
            if remaining > 0:
                long_lots.append(_Lot(quantity=remaining, price=price, fees=fees))
        else:
            remaining = qty
            while remaining > 0 and long_lots:
                lot = long_lots[0]
                matched = min(remaining, lot.quantity)
                realized += (price - lot.price) * matched * mult
                lot.quantity -= matched
                remaining -= matched
                if lot.quantity <= 0:
                    long_lots.pop(0)
            if remaining > 0:
                short_lots.append(_Lot(quantity=remaining, price=price, fees=fees))

    return realized, fees_total


def compute_trading_summary(
    fills: list[ImportedFillView],
    *,
    has_account_snapshots: bool,
) -> TradingSummary:
    trusted = [f for f in fills if f.is_complete]
    incomplete_count = sum(1 for f in fills if not f.is_complete)

    groups: dict[str, list[ImportedFillView]] = {}
    for fill in trusted:
        key = str(fill.instrument_id or fill.symbol_raw.upper())
        groups.setdefault(key, []).append(fill)

    lines: list[RealizedPnLLine] = []
    total_realized = Decimal(0)
    total_fees = Decimal(0)

    for group_fills in groups.values():
        realized, fees = _realized_for_group(group_fills)
        sample = group_fills[0]
        lines.append(
            RealizedPnLLine(
                instrument_id=sample.instrument_id,
                symbol=sample.instrument_symbol or sample.symbol_raw,
                asset_class=sample.asset_class,
                contract_code=sample.contract_code,
                currency=sample.currency,
                realized_pnl=realized,
                fees=fees,
                net_pnl=realized - fees,
                fill_count=len(group_fills),
            )
        )
        total_realized += realized
        total_fees += fees

    lines.sort(key=lambda line: line.symbol)
    total_net = total_realized - total_fees

    return TradingSummary(
        lines=tuple(lines),
        total_realized_pnl=total_realized,
        total_fees=total_fees,
        total_net_pnl=total_net,
        trusted_fill_count=len(trusted),
        incomplete_fill_count=incomplete_count,
        has_account_snapshots=has_account_snapshots,
        portfolio_return_available=False,
    )


async def trading_summary_for_owner(
    conn: AsyncConnection,
    owner_id: UUID,
    *,
    asset_class: str | None = None,
    instrument_id: UUID | None = None,
) -> TradingSummary:
    fills = await list_fills_for_owner(
        conn,
        owner_id,
        asset_class=asset_class,
        instrument_id=instrument_id,
        trusted_only=False,
        limit=5000,
    )
    snapshot_row = await fetch_all(
        conn,
        "select id from account_snapshots where owner_id = :owner_id limit 1",
        {"owner_id": owner_id},
    )
    has_snapshots = len(snapshot_row) > 0
    return compute_trading_summary(fills, has_account_snapshots=has_snapshots)
