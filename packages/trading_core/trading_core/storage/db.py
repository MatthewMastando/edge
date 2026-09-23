"""Async Postgres access for repositories, the job runner and the API.

SQLAlchemy Core executes bound SQL through asyncpg. Callers own transactions via
``engine.begin()``; repository functions never open a connection themselves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from sqlalchemy import CursorResult, TextClause, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.engine import RowMapping

T = TypeVar("T")


def to_async_url(url: str) -> str:
    """Turn a libpq URL into the SQLAlchemy asyncio driver URL."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url[len("postgresql+psycopg://") :]
    prefix = "postgresql://"
    if url.startswith(prefix):
        return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(to_async_url(url), pool_pre_ping=True)

    async def dispose(self) -> None:
        await self.engine.dispose()


def _row(mapping: RowMapping) -> dict[str, object]:
    return {str(key): value for key, value in mapping.items()}


async def fetch_one(
    conn: AsyncConnection, sql: str, params: Mapping[str, object] | None = None
) -> dict[str, object] | None:
    result = await conn.execute(text(sql), dict(params or {}))
    row = result.mappings().first()
    if row is None:
        return None
    return _row(row)


async def fetch_all(
    conn: AsyncConnection, sql: str, params: Mapping[str, object] | None = None
) -> list[dict[str, object]]:
    result = await conn.execute(text(sql), dict(params or {}))
    return [_row(row) for row in result.mappings().all()]


async def execute(
    conn: AsyncConnection, sql: str, params: Mapping[str, object] | None = None
) -> CursorResult[tuple[object, ...]]:
    statement: TextClause = text(sql)
    return await conn.execute(statement, dict(params or {}))
