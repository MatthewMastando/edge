"""Read-only market reference and snapshot data served from the fixture adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from trading_api.auth import UserDep
from trading_api.dependencies import FixtureAdapterDep
from trading_core.data.adapter import AdapterCapabilities, BarsRequest, UnknownSymbolError
from trading_core.domain.common import Timeframe
from trading_core.domain.instruments import FuturesContract, Instrument, SessionCalendar
from trading_core.domain.market import BarSeries, MarketSnapshot

router = APIRouter(prefix="/v1", tags=["market"])


@router.get("/capabilities", response_model=AdapterCapabilities, operation_id="getCapabilities")
async def get_capabilities(adapter: FixtureAdapterDep, _user: UserDep) -> AdapterCapabilities:
    return adapter.capabilities


@router.get("/instruments", response_model=list[Instrument], operation_id="listInstruments")
async def list_instruments(adapter: FixtureAdapterDep, _user: UserDep) -> list[Instrument]:
    return await adapter.list_instruments()


@router.get(
    "/futures-contracts",
    response_model=list[FuturesContract],
    operation_id="listFuturesContracts",
)
async def list_futures_contracts(
    adapter: FixtureAdapterDep,
    _user: UserDep,
    root: Annotated[str | None, Query(max_length=8)] = None,
) -> list[FuturesContract]:
    return await adapter.list_futures_contracts(root)


@router.get(
    "/session-calendars", response_model=list[SessionCalendar], operation_id="listSessionCalendars"
)
async def list_session_calendars(
    adapter: FixtureAdapterDep, _user: UserDep
) -> list[SessionCalendar]:
    return list(adapter.manifest.session_calendars)


@router.get("/snapshots", response_model=list[MarketSnapshot], operation_id="listSnapshots")
async def list_snapshots(adapter: FixtureAdapterDep, _user: UserDep) -> list[MarketSnapshot]:
    return list(adapter.manifest.snapshots)


@router.get("/bars", response_model=BarSeries, operation_id="getBars")
async def get_bars(
    adapter: FixtureAdapterDep,
    _user: UserDep,
    symbol: Annotated[str, Query(min_length=1, max_length=16, examples=["6EZ6", "SPY"])],
    timeframe: Timeframe = "5m",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=50_000)] = 500,
) -> BarSeries:
    try:
        return await adapter.get_bars(
            BarsRequest(symbol=symbol, timeframe=timeframe, start=start, end=end, limit=limit)
        )
    except UnknownSymbolError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
