"""Manifest written next to generated Parquet files."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from pydantic import Field

from trading_core.domain.common import (
    DataRevision,
    DomainModel,
    FixtureLabel,
    Timeframe,
    UtcDatetime,
)
from trading_core.domain.instruments import (
    FuturesContract,
    Instrument,
    RollMapEntry,
    SessionCalendar,
)
from trading_core.domain.market import MarketSnapshot

if TYPE_CHECKING:
    from pathlib import Path

MANIFEST_FILENAME = "manifest.json"


class FixtureManifest(DomainModel):
    label: FixtureLabel
    data_revision: DataRevision
    seed: int
    start_date: date
    session_days: int = Field(ge=1)
    timeframe: Timeframe
    as_of: UtcDatetime = Field(description="Close time of the last generated bar.")
    inputs_hash: str
    instruments: list[Instrument]
    futures_contracts: list[FuturesContract]
    roll_maps: list[RollMapEntry]
    session_calendars: list[SessionCalendar]
    snapshots: list[MarketSnapshot]

    def snapshot_for(self, *, symbol: str, kind: str) -> MarketSnapshot | None:
        for snapshot in self.snapshots:
            if (
                snapshot.kind == kind
                and (snapshot.contract_code or _symbol_of(self, snapshot)) == symbol
            ):
                return snapshot
        return None


def _symbol_of(manifest: FixtureManifest, snapshot: MarketSnapshot) -> str:
    for instrument in manifest.instruments:
        if instrument.id == snapshot.instrument_id:
            return instrument.symbol
    return ""


def write_manifest(root: Path, manifest: FixtureManifest) -> Path:
    path = root / MANIFEST_FILENAME
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def read_manifest(root: Path) -> FixtureManifest:
    path = root / MANIFEST_FILENAME
    if not path.is_file():
        msg = f"no fixture manifest at {path}; run `uv run trading-core fixtures generate` first"
        raise FileNotFoundError(msg)
    return FixtureManifest.model_validate_json(path.read_text(encoding="utf-8"))
