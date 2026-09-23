"""My Trading: imported fills and realized P&L summaries."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from trading_api.auth import UserDep
from trading_api.dependencies import DatabaseDep
from trading_core.domain.trading_records import ImportedFillView, TradingSummary
from trading_core.imports.pnl import list_fills_for_owner, trading_summary_for_owner

router = APIRouter(prefix="/v1/trading", tags=["trading"])


@router.get("/fills", response_model=list[ImportedFillView], operation_id="listImportedFills")
async def list_fills(
    database: DatabaseDep,
    user: UserDep,
    asset_class: Annotated[str | None, Query(max_length=32)] = None,
    instrument_id: Annotated[UUID | None, Query()] = None,
    trusted_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> list[ImportedFillView]:
    async with database.engine.begin() as conn:
        return await list_fills_for_owner(
            conn,
            user.id,
            asset_class=asset_class,
            instrument_id=instrument_id,
            trusted_only=trusted_only,
            limit=limit,
        )


@router.get("/summary", response_model=TradingSummary, operation_id="getTradingSummary")
async def get_summary(
    database: DatabaseDep,
    user: UserDep,
    asset_class: Annotated[str | None, Query(max_length=32)] = None,
    instrument_id: Annotated[UUID | None, Query()] = None,
) -> TradingSummary:
    async with database.engine.begin() as conn:
        return await trading_summary_for_owner(
            conn,
            user.id,
            asset_class=asset_class,
            instrument_id=instrument_id,
        )
