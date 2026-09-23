from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from trading_api import __version__
from trading_api.settings import ApiSettings, get_settings
from trading_core.data.fixture import FixtureAdapter
from trading_core.domain.common import DomainModel

router = APIRouter(tags=["health"])


class HealthResponse(DomainModel):
    status: Literal["ok"]
    service: str
    version: str
    mode: Literal["fixture", "live"]
    provenance: Literal["fixture", "recorded", "live"] = Field(
        description="Provenance of data this deployment serves by default."
    )
    fixtures_loaded: bool
    data_revision: str | None = None
    order_write_capability: Literal[False] = Field(
        default=False, description="Always false: the MVP has no broker order-write path."
    )


@router.get("/health", response_model=HealthResponse, operation_id="getHealth")
def get_health(
    request: Request, settings: Annotated[ApiSettings, Depends(get_settings)]
) -> HealthResponse:
    adapter: FixtureAdapter | None = getattr(request.app.state, "fixture_adapter", None)
    return HealthResponse(
        status="ok",
        service="trading-api",
        version=__version__,
        mode=settings.mode,
        provenance="fixture" if settings.mode == "fixture" else "live",
        fixtures_loaded=adapter is not None,
        data_revision=adapter.manifest.data_revision if adapter else None,
    )
