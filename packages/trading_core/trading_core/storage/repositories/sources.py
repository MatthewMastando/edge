"""Sources and citable excerpts."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from trading_core.research.interfaces import SourceExcerpt, SourceKind
from trading_core.storage.db import fetch_all, fetch_one
from trading_core.storage.repositories.common import (
    as_datetime,
    as_datetime_or_none,
    as_str,
    as_str_or_none,
    as_uuid,
    uuid_array,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from trading_core.domain.common import Provenance, UtcDatetime


async def insert_source(
    conn: AsyncConnection,
    *,
    kind: SourceKind,
    url: str | None,
    title: str | None,
    publisher: str | None,
    published_at: UtcDatetime | None,
    retrieved_at: UtcDatetime,
    provider: str,
    provenance: Provenance,
    content_hash: str | None = None,
    status: str = "ok",
    error: str | None = None,
    source_id: UUID | None = None,
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into sources (
          id, kind, url, title, publisher, published_at, retrieved_at, provider, provenance,
          content_hash, status, error
        ) values (
          :id, :kind, :url, :title, :publisher, :published_at, :retrieved_at, :provider,
          :provenance, :content_hash, :status, :error
        )
        returning id
        """,
        {
            "id": source_id or uuid4(),
            "kind": kind,
            "url": url,
            "title": title,
            "publisher": publisher,
            "published_at": published_at,
            "retrieved_at": retrieved_at,
            "provider": provider,
            "provenance": provenance,
            "content_hash": content_hash,
            "status": status,
            "error": error,
        },
    )
    if row is None:
        msg = "source insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


async def insert_excerpt(
    conn: AsyncConnection,
    *,
    source_id: UUID,
    text: str,
    published_at: UtcDatetime | None,
    retrieved_at: UtcDatetime,
    provenance: Provenance,
    excerpt_id: UUID | None = None,
    url: str | None = None,
    kind: SourceKind = "web_page",
) -> SourceExcerpt:
    new_id = excerpt_id or uuid4()
    clipped = text[:4000]
    row = await fetch_one(
        conn,
        """
        insert into source_excerpts (
          id, source_id, text, published_at, retrieved_at, provenance
        ) values (
          :id, :source_id, :text, :published_at, :retrieved_at, :provenance
        )
        returning id, source_id, text, published_at, retrieved_at, provenance
        """,
        {
            "id": new_id,
            "source_id": source_id,
            "text": clipped,
            "published_at": published_at,
            "retrieved_at": retrieved_at,
            "provenance": provenance,
        },
    )
    if row is None:
        msg = "excerpt insert returned no row"
        raise RuntimeError(msg)
    return SourceExcerpt(
        id=as_uuid(row["id"]),
        source_id=as_uuid(row["source_id"]),
        kind=kind,
        text=as_str(row["text"]),
        url=url,
        published_at=as_datetime_or_none(row["published_at"]),
        retrieved_at=as_datetime(row["retrieved_at"]),
        provenance=provenance,
    )


async def existing_source_ids(conn: AsyncConnection, source_ids: list[UUID]) -> set[UUID]:
    if not source_ids:
        return set()
    rows = await fetch_all(
        conn,
        "select id from sources where id = any(cast(string_to_array(:ids, ',') as uuid[]))",
        {"ids": uuid_array(source_ids)},
    )
    return {as_uuid(row["id"]) for row in rows}


async def existing_excerpt_ids(conn: AsyncConnection, excerpt_ids: list[UUID]) -> set[UUID]:
    if not excerpt_ids:
        return set()
    rows = await fetch_all(
        conn,
        """
        select id from source_excerpts
        where id = any(cast(string_to_array(:ids, ',') as uuid[]))
        """,
        {"ids": uuid_array(excerpt_ids)},
    )
    return {as_uuid(row["id"]) for row in rows}


async def get_excerpt_text(conn: AsyncConnection, excerpt_id: UUID) -> str | None:
    row = await fetch_one(
        conn, "select text from source_excerpts where id = :id", {"id": excerpt_id}
    )
    if row is None:
        return None
    return as_str_or_none(row["text"])
