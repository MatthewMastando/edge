"""Saved CSV mapping presets (stored in settings, not a fixed broker parser)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from trading_core.domain.trading_records import ImportPreset

if TYPE_CHECKING:
    from pydantic import JsonValue

PRESET_SETTINGS_KEY = "csv_import_presets"


def presets_from_setting(value: dict[str, JsonValue] | None) -> list[ImportPreset]:
    if value is None:
        return []
    raw = value.get("presets")
    if not isinstance(raw, list):
        return []
    out: list[ImportPreset] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(ImportPreset.model_validate(item))
            except ValidationError:
                continue
    return out


def presets_to_setting(presets: list[ImportPreset]) -> dict[str, JsonValue]:
    return {"presets": [preset.model_dump(mode="json") for preset in presets]}
