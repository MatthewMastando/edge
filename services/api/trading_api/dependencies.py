"""Request-scoped dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from trading_api.settings import ApiSettings, get_settings
from trading_core.data.fixture import FixtureAdapter
from trading_core.storage.db import Database


def get_app_settings(request: Request) -> ApiSettings:
    """Settings the running app was created with (falls back to the environment)."""
    settings: ApiSettings | None = getattr(request.app.state, "settings", None)
    return settings or get_settings()


SettingsDep = Annotated[ApiSettings, Depends(get_app_settings)]


def get_fixture_adapter(request: Request) -> FixtureAdapter:
    adapter: FixtureAdapter | None = getattr(request.app.state, "fixture_adapter", None)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Fixture data is not generated. Run `uv run trading-core fixtures generate` "
                "or point TRW_FIXTURES_ROOT at a generated directory."
            ),
        )
    return adapter


FixtureAdapterDep = Annotated[FixtureAdapter, Depends(get_fixture_adapter)]


def get_database(request: Request) -> Database:
    database: Database | None = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured.",
        )
    return database


DatabaseDep = Annotated[Database, Depends(get_database)]
