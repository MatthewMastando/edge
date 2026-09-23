"""Mapping-driven CSV import (preview, commit, saved presets)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import Field

from trading_api.auth import UserDep
from trading_api.dependencies import DatabaseDep
from trading_core.domain.common import DomainModel
from trading_core.domain.trading_records import (
    CsvColumnMapping,
    ImportCommitResult,
    ImportPreset,
    ImportPreview,
)
from trading_core.imports.csv import build_import_preview, commit_import
from trading_core.imports.mapping import (
    PRESET_SETTINGS_KEY,
    presets_from_setting,
    presets_to_setting,
)
from trading_core.imports.pnl import InstrumentLookup
from trading_core.storage.repositories import analytics

router = APIRouter(prefix="/v1/import", tags=["import"])


class ImportPreviewRequest(DomainModel):
    filename: str = Field(max_length=255)
    csv_text: str = Field(max_length=2_000_000)
    mapping: CsvColumnMapping


class ImportCommitRequest(DomainModel):
    filename: str = Field(max_length=255)
    csv_text: str = Field(max_length=2_000_000)
    mapping: CsvColumnMapping


class PresetList(DomainModel):
    presets: tuple[ImportPreset, ...]


class SavePresetRequest(DomainModel):
    preset: ImportPreset


@router.get("/presets", response_model=PresetList, operation_id="listImportPresets")
async def list_presets(database: DatabaseDep, _user: UserDep) -> PresetList:
    async with database.engine.begin() as conn:
        raw = await analytics.get_setting(conn, PRESET_SETTINGS_KEY)
    return PresetList(presets=tuple(presets_from_setting(raw)))


@router.put(
    "/presets/{name}",
    response_model=ImportPreset,
    operation_id="saveImportPreset",
)
async def save_preset(
    name: Annotated[str, Field(max_length=120)],
    body: SavePresetRequest,
    database: DatabaseDep,
    _user: UserDep,
) -> ImportPreset:
    if body.preset.name != name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Preset name mismatch")
    async with database.engine.begin() as conn:
        raw = await analytics.get_setting(conn, PRESET_SETTINGS_KEY)
        presets = presets_from_setting(raw)
        updated = [p for p in presets if p.name != name]
        updated.append(body.preset)
        await analytics.set_setting(
            conn,
            key=PRESET_SETTINGS_KEY,
            value=presets_to_setting(updated),
            description="Saved CSV column mapping presets for personal history import",
        )
    return body.preset


@router.post("/preview", response_model=ImportPreview, operation_id="previewCsvImport")
async def preview_import(
    body: ImportPreviewRequest,
    database: DatabaseDep,
    user: UserDep,
) -> ImportPreview:
    async with database.engine.begin() as conn:
        lookup = await InstrumentLookup.load(conn)
        hashes = await analytics.existing_fill_hashes(conn, user.id)
    return build_import_preview(
        filename=body.filename,
        csv_text=body.csv_text,
        mapping=body.mapping,
        lookup=lookup,
        existing_hashes=hashes,
    )


@router.post("/commit", response_model=ImportCommitResult, operation_id="commitCsvImport")
async def commit_csv_import(
    body: ImportCommitRequest,
    database: DatabaseDep,
    user: UserDep,
) -> ImportCommitResult:
    async with database.engine.begin() as conn:
        lookup = await InstrumentLookup.load(conn)
        hashes = await analytics.existing_fill_hashes(conn, user.id)
        return await commit_import(
            conn,
            owner_id=user.id,
            filename=body.filename,
            mapping=body.mapping,
            csv_text=body.csv_text,
            lookup=lookup,
            existing_hashes=hashes,
        )
