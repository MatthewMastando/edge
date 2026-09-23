"""Read-only Kalshi markets and sourced event briefs (fixture fallback)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from trading_api.auth import UserDep
from trading_api.dependencies import get_app_settings
from trading_core.domain.trading_records import KalshiEventBrief, KalshiMarket
from trading_core.kalshi.service import KalshiService

router = APIRouter(prefix="/v1/kalshi", tags=["kalshi"])


def _kalshi(request: Request) -> KalshiService:
    settings = get_app_settings(request)
    return KalshiService(use_live=settings.mode == "live")


@router.get("/markets", response_model=list[KalshiMarket], operation_id="listKalshiMarkets")
async def list_markets(
    request: Request,
    _user: UserDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[KalshiMarket]:
    service = _kalshi(request)
    return await service.list_markets(limit=limit)


@router.get(
    "/markets/{ticker}/brief",
    response_model=KalshiEventBrief,
    operation_id="getKalshiEventBrief",
)
async def get_brief(ticker: str, request: Request, _user: UserDep) -> KalshiEventBrief:
    service = _kalshi(request)
    brief = await service.event_brief(ticker)
    if brief is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Market not found")
    return brief
