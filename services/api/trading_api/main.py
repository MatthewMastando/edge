"""Application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from trading_api import __version__
from trading_api.openapi_schema import build_openapi
from trading_api.routes import (
    artifacts,
    chat,
    health,
    imports,
    kalshi,
    market,
    runs,
    search,
    trading,
)
from trading_api.settings import ApiSettings, get_settings
from trading_core.data.fixture import FixtureAdapter
from trading_core.storage.db import Database

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

log = logging.getLogger("trading_api")

DESCRIPTION = (
    "Research-only API for the Trading Research Workspace. Serves shared contracts, fixture market "
    "data and (from Stage 1B) chat, runs and artifacts. There is no broker order-write capability."
)


def load_fixture_adapter(settings: ApiSettings) -> FixtureAdapter | None:
    try:
        return FixtureAdapter(settings.fixtures_root)
    except FileNotFoundError:
        log.warning(
            "fixture manifest not found at %s; market routes return 503 until generated",
            settings.fixtures_root,
        )
        return None


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("starting trading-api %s with %s", __version__, settings.redacted)
        database = Database(settings.database_url)
        app.state.settings = settings
        app.state.database = database
        app.state.fixture_adapter = load_fixture_adapter(settings)
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(
        title="Trading Research Workspace API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        separate_input_output_schemas=False,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(health.router)
    app.include_router(market.router)
    app.include_router(chat.router)
    app.include_router(runs.router)
    app.include_router(artifacts.router)
    app.include_router(search.router)
    app.include_router(imports.router)
    app.include_router(trading.router)
    app.include_router(kalshi.router)

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = build_openapi(app)
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app


app = create_app()
