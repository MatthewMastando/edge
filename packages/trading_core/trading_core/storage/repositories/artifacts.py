"""Artifacts, immutable revisions and the single autosaved draft."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from trading_core.storage.db import fetch_all, fetch_one
from trading_core.storage.repositories.common import (
    as_int,
    as_json_dict,
    as_str,
    as_uuid,
    json_param,
    like_pattern,
    text_array,
)

if TYPE_CHECKING:
    from pydantic import JsonValue
    from sqlalchemy.ext.asyncio import AsyncConnection


async def insert_artifact(
    conn: AsyncConnection,
    *,
    owner_id: UUID,
    conversation_id: UUID | None,
    kind: str,
    title: str,
    instrument_id: UUID | None,
    contract_code: str | None,
    tags: list[str],
    artifact_id: UUID | None = None,
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into artifacts (
          id, owner_id, conversation_id, kind, title, tags, instrument_id, contract_code
        ) values (
          :id, :owner_id, :conversation_id, :kind, :title,
          cast(string_to_array(:tags, E'\\x1f') as text[]),
          :instrument_id, :contract_code
        )
        returning id
        """,
        {
            "id": artifact_id or uuid4(),
            "owner_id": owner_id,
            "conversation_id": conversation_id,
            "kind": kind,
            "title": title,
            "tags": text_array(tags),
            "instrument_id": instrument_id,
            "contract_code": contract_code,
        },
    )
    if row is None:
        msg = "artifact insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


async def get_artifact(
    conn: AsyncConnection, artifact_id: UUID, owner_id: UUID
) -> dict[str, object] | None:
    return await fetch_one(
        conn,
        """
        select id, owner_id, conversation_id, kind, title, tags, instrument_id, contract_code,
               current_revision_id, created_at, updated_at
        from artifacts
        where id = :id and owner_id = :owner_id and archived_at is null
        """,
        {"id": artifact_id, "owner_id": owner_id},
    )


async def list_artifacts(
    conn: AsyncConnection, owner_id: UUID, *, limit: int = 50
) -> list[dict[str, object]]:
    return await fetch_all(
        conn,
        """
        select id, title, kind, tags, instrument_id, contract_code, current_revision_id, updated_at
        from artifacts
        where owner_id = :owner_id and archived_at is null
        order by updated_at desc
        limit :limit
        """,
        {"owner_id": owner_id, "limit": limit},
    )


async def search_artifacts(
    conn: AsyncConnection, owner_id: UUID, query: str, *, limit: int = 20
) -> list[dict[str, object]]:
    return await fetch_all(
        conn,
        """
        select id, title, kind, updated_at
        from artifacts
        where owner_id = :owner_id
          and archived_at is null
          and (
            title ilike :pattern escape '\\'
            or :query = any(tags)
          )
        order by updated_at desc
        limit :limit
        """,
        {
            "owner_id": owner_id,
            "pattern": like_pattern(query),
            "query": query,
            "limit": limit,
        },
    )


async def lock_artifact(conn: AsyncConnection, artifact_id: UUID, owner_id: UUID) -> bool:
    row = await fetch_one(
        conn,
        """
        select id from artifacts
        where id = :id and owner_id = :owner_id
        for update
        """,
        {"id": artifact_id, "owner_id": owner_id},
    )
    return row is not None


async def generated_revision_for_run(
    conn: AsyncConnection, run_id: UUID
) -> tuple[UUID, UUID] | None:
    """Revision id and artifact id already written for this run, if any."""
    row = await fetch_one(
        conn,
        """
        select id, artifact_id
        from artifact_revisions
        where run_id = :run_id and change_kind = 'generated'
        order by revision_number asc
        limit 1
        """,
        {"run_id": run_id},
    )
    if row is None:
        return None
    return as_uuid(row["id"]), as_uuid(row["artifact_id"])


async def insert_revision(
    conn: AsyncConnection,
    *,
    artifact_id: UUID,
    parent_revision_id: UUID | None,
    run_id: UUID | None,
    structured: dict[str, JsonValue],
    presentation_markdown: str,
    change_kind: str,
    created_by: str,
    is_demonstration: bool,
    provenance: str,
) -> tuple[UUID, int]:
    row = await fetch_one(
        conn,
        """
        insert into artifact_revisions (
          artifact_id, revision_number, parent_revision_id, run_id, structured,
          presentation_markdown, change_kind, created_by, is_demonstration, provenance
        )
        select :artifact_id,
               coalesce(max(revision_number), 0) + 1,
               :parent_revision_id,
               :run_id,
               cast(:structured as jsonb),
               :presentation_markdown,
               :change_kind,
               :created_by,
               :is_demonstration,
               :provenance
        from artifact_revisions
        where artifact_id = :artifact_id
        returning id, revision_number
        """,
        {
            "artifact_id": artifact_id,
            "parent_revision_id": parent_revision_id,
            "run_id": run_id,
            "structured": json_param(structured),
            "presentation_markdown": presentation_markdown,
            "change_kind": change_kind,
            "created_by": created_by,
            "is_demonstration": is_demonstration,
            "provenance": provenance,
        },
    )
    if row is None:
        msg = "revision insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"]), as_int(row["revision_number"])


async def set_current_revision(conn: AsyncConnection, artifact_id: UUID, revision_id: UUID) -> None:
    await fetch_one(
        conn,
        """
        update artifacts set current_revision_id = :revision_id
        where id = :artifact_id
        returning id
        """,
        {"artifact_id": artifact_id, "revision_id": revision_id},
    )


async def list_revisions(
    conn: AsyncConnection, artifact_id: UUID, *, limit: int = 50
) -> list[dict[str, object]]:
    return await fetch_all(
        conn,
        """
        select id, revision_number, change_kind, created_by, is_demonstration, provenance,
               created_at, presentation_markdown
        from artifact_revisions
        where artifact_id = :artifact_id
        order by revision_number desc
        limit :limit
        """,
        {"artifact_id": artifact_id, "limit": limit},
    )


async def get_revision(conn: AsyncConnection, revision_id: UUID) -> dict[str, object] | None:
    return await fetch_one(
        conn,
        """
        select id, artifact_id, revision_number, parent_revision_id, run_id, structured,
               presentation_markdown, change_kind, created_by, is_demonstration, provenance,
               created_at
        from artifact_revisions
        where id = :id
        """,
        {"id": revision_id},
    )


async def latest_structured(
    conn: AsyncConnection, artifact_id: UUID
) -> dict[str, JsonValue] | None:
    row = await fetch_one(
        conn,
        """
        select structured from artifact_revisions
        where artifact_id = :artifact_id
        order by revision_number desc
        limit 1
        """,
        {"artifact_id": artifact_id},
    )
    if row is None:
        return None
    return as_json_dict(row["structured"])


async def upsert_draft(
    conn: AsyncConnection,
    *,
    artifact_id: UUID,
    base_revision_id: UUID | None,
    structured: dict[str, JsonValue] | None,
    presentation_markdown: str | None,
) -> None:
    await fetch_one(
        conn,
        """
        insert into artifact_drafts (
          artifact_id, base_revision_id, structured, presentation_markdown
        ) values (
          :artifact_id, :base_revision_id, cast(:structured as jsonb), :presentation_markdown
        )
        on conflict (artifact_id) do update set
          base_revision_id = excluded.base_revision_id,
          structured = excluded.structured,
          presentation_markdown = excluded.presentation_markdown,
          updated_at = now()
        returning artifact_id
        """,
        {
            "artifact_id": artifact_id,
            "base_revision_id": base_revision_id,
            "structured": json_param(structured) if structured is not None else None,
            "presentation_markdown": presentation_markdown,
        },
    )


async def get_draft(conn: AsyncConnection, artifact_id: UUID) -> dict[str, object] | None:
    return await fetch_one(
        conn,
        """
        select artifact_id, base_revision_id, structured, presentation_markdown, updated_at
        from artifact_drafts
        where artifact_id = :artifact_id
        """,
        {"artifact_id": artifact_id},
    )


async def insert_proposed_edit(
    conn: AsyncConnection,
    *,
    artifact_id: UUID,
    base_revision_id: UUID,
    run_id: UUID | None,
    proposal: dict[str, JsonValue],
) -> UUID:
    row = await fetch_one(
        conn,
        """
        insert into artifact_proposed_edits (artifact_id, base_revision_id, run_id, proposal)
        values (:artifact_id, :base_revision_id, :run_id, cast(:proposal as jsonb))
        returning id
        """,
        {
            "artifact_id": artifact_id,
            "base_revision_id": base_revision_id,
            "run_id": run_id,
            "proposal": json_param(proposal),
        },
    )
    if row is None:
        msg = "proposed edit insert returned no row"
        raise RuntimeError(msg)
    return as_uuid(row["id"])


def revision_number(row: dict[str, object]) -> int:
    return as_int(row["revision_number"])


def artifact_title(row: dict[str, object]) -> str:
    return as_str(row["title"])
