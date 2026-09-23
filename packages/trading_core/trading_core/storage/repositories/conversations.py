"""Conversations and messages."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from trading_core.storage.db import fetch_all, fetch_one
from trading_core.storage.repositories.common import (
    as_datetime,
    as_json_dict,
    as_str,
    as_str_or_none,
    as_uuid,
    json_param,
    like_pattern,
)

if TYPE_CHECKING:
    from datetime import datetime

    from pydantic import JsonValue
    from sqlalchemy.ext.asyncio import AsyncConnection


async def insert_conversation(
    conn: AsyncConnection,
    *,
    owner_id: UUID,
    title: str | None,
    context: dict[str, JsonValue],
    conversation_id: UUID | None = None,
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into conversations (id, owner_id, title, context)
        values (:id, :owner_id, :title, cast(:context as jsonb))
        returning id
        """,
        {
            "id": conversation_id or uuid4(),
            "owner_id": owner_id,
            "title": title,
            "context": json_param(context),
        },
    )
    if row is None:
        msg = "conversation insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


async def get_conversation(
    conn: AsyncConnection, conversation_id: UUID, owner_id: UUID
) -> dict[str, object] | None:
    return await fetch_one(
        conn,
        """
        select id, owner_id, title, context, created_at, updated_at
        from conversations
        where id = :id and owner_id = :owner_id and archived_at is null
        """,
        {"id": conversation_id, "owner_id": owner_id},
    )


async def list_conversations(
    conn: AsyncConnection, owner_id: UUID, *, limit: int = 50
) -> list[dict[str, object]]:
    return await fetch_all(
        conn,
        """
        select id, title, created_at, updated_at
        from conversations
        where owner_id = :owner_id and archived_at is null
        order by updated_at desc
        limit :limit
        """,
        {"owner_id": owner_id, "limit": limit},
    )


async def insert_message(
    conn: AsyncConnection,
    *,
    conversation_id: UUID,
    role: str,
    content: str,
    run_id: UUID | None = None,
    metadata: dict[str, JsonValue] | None = None,
    message_id: UUID | None = None,
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into messages (id, conversation_id, role, content, run_id, metadata)
        values (:id, :conversation_id, :role, :content, :run_id, cast(:metadata as jsonb))
        returning id
        """,
        {
            "id": message_id or uuid4(),
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "run_id": run_id,
            "metadata": json_param(metadata or {}),
        },
    )
    if row is None:
        msg = "message insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


async def insert_assistant_once(
    conn: AsyncConnection,
    *,
    conversation_id: UUID | None,
    run_id: UUID,
    content: str,
    is_demonstration: bool,
) -> None:
    if conversation_id is None:
        return
    existing = await fetch_one(
        conn,
        """
        select id from messages
        where run_id = :run_id and role = 'assistant'
        limit 1
        """,
        {"run_id": run_id},
    )
    if existing is not None:
        return
    await insert_message(
        conn,
        conversation_id=conversation_id,
        role="assistant",
        content=content,
        run_id=run_id,
        metadata={"is_demonstration": is_demonstration},
    )


async def list_messages(
    conn: AsyncConnection, conversation_id: UUID, *, limit: int = 200
) -> list[dict[str, object]]:
    return await fetch_all(
        conn,
        """
        select id, role, content, run_id, created_at
        from messages
        where conversation_id = :conversation_id
        order by created_at asc
        limit :limit
        """,
        {"conversation_id": conversation_id, "limit": limit},
    )


async def search_conversations(
    conn: AsyncConnection, owner_id: UUID, query: str, *, limit: int = 20
) -> list[dict[str, object]]:
    return await fetch_all(
        conn,
        """
        select id, title, updated_at
        from conversations
        where owner_id = :owner_id
          and archived_at is null
          and title ilike :pattern escape '\\'
        order by updated_at desc
        limit :limit
        """,
        {"owner_id": owner_id, "pattern": like_pattern(query), "limit": limit},
    )


def conversation_title(row: dict[str, object]) -> str | None:
    return as_str_or_none(row["title"])


def conversation_updated_at(row: dict[str, object]) -> datetime:
    return as_datetime(row["updated_at"])


def message_content(row: dict[str, object]) -> str:
    return as_str(row["content"])


def conversation_context(row: dict[str, object]) -> dict[str, JsonValue]:
    return as_json_dict(row["context"])
