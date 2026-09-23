"""Typed loaders for the YAML fixture definitions under ``fixtures/``."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, time
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from trading_core.domain.common import AssetClass, DecimalStr
from trading_core.domain.instruments import (
    FuturesContract,
    Instrument,
    RollMapEntry,
    RollMethod,
    SessionCalendar,
    SettlementType,
)

FIXTURE_NAMESPACE = uuid.UUID("6f1c0d9e-3a8b-4c1e-9d2f-7b5a1e0c4d33")
"""Namespace for deterministic fixture ids (uuid5). Never reuse for live rows."""

DEFAULT_FIXTURES_DIR = Path("fixtures")


def fixture_uuid(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(FIXTURE_NAMESPACE, f"{kind}:{key}")


class _SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GeneratorParams(_SpecModel):
    """Per-instrument knobs for the synthetic price process."""

    start_price: DecimalStr
    step_ticks_sd: float = Field(gt=0, description="Std dev of per-trade move, in ticks.")
    trades_per_bar: float = Field(gt=0, description="Poisson mean of prints per 5-minute bar.")
    size_min: float = Field(gt=0)
    size_max: float = Field(gt=0)
    size_decimals: int = Field(ge=0, le=8)
    coverage_note: str | None = None


class InstrumentSpec(_SpecModel):
    symbol: str
    name: str
    asset_class: AssetClass
    venue: str
    currency: str
    tick_size: DecimalStr
    tick_value: DecimalStr
    multiplier: DecimalStr
    session_calendar_id: str
    base_asset: str | None = None
    quote_asset: str | None = None
    fixture: GeneratorParams

    def to_instrument(self) -> Instrument:
        return Instrument(
            id=fixture_uuid("instrument", self.symbol),
            symbol=self.symbol,
            name=self.name,
            asset_class=self.asset_class,
            venue=self.venue,
            currency=self.currency,
            tick_size=self.tick_size,
            tick_value=self.tick_value,
            multiplier=self.multiplier,
            session_calendar_id=self.session_calendar_id,
            base_asset=self.base_asset,
            quote_asset=self.quote_asset,
            is_continuous=False,
            provenance="fixture",
        )


class FuturesContractSpec(_SpecModel):
    contract_code: str
    root: str
    exchange: str
    contract_month: str
    expiry_date: date
    last_trade_date: date
    last_trade_time_local: time | None = None
    first_notice_date: date | None = None
    tick_size: DecimalStr
    tick_value: DecimalStr
    point_multiplier: DecimalStr
    currency: str
    session_calendar_id: str
    settlement_type: SettlementType
    settlement_time_local: time | None = None

    def to_contract(self) -> FuturesContract:
        return FuturesContract(
            id=fixture_uuid("futures_contract", self.contract_code),
            instrument_id=fixture_uuid("instrument", self.root),
            root=self.root,
            contract_code=self.contract_code,
            exchange=self.exchange,
            contract_month=self.contract_month,
            expiry_date=self.expiry_date,
            last_trade_date=self.last_trade_date,
            last_trade_time_local=self.last_trade_time_local,
            first_notice_date=self.first_notice_date,
            tick_size=self.tick_size,
            tick_value=self.tick_value,
            point_multiplier=self.point_multiplier,
            currency=self.currency,
            session_calendar_id=self.session_calendar_id,
            settlement_type=self.settlement_type,
            settlement_time_local=self.settlement_time_local,
            is_active=True,
            provenance="fixture",
        )


class RollSpec(_SpecModel):
    root: str
    from_contract_code: str
    to_contract_code: str
    roll_date: date
    method: RollMethod
    adjustment: DecimalStr | None = None

    def to_entry(self) -> RollMapEntry:
        return RollMapEntry(
            id=fixture_uuid("roll", f"{self.from_contract_code}->{self.to_contract_code}"),
            instrument_id=fixture_uuid("instrument", self.root),
            root=self.root,
            from_contract_code=self.from_contract_code,
            to_contract_code=self.to_contract_code,
            roll_date=self.roll_date,
            method=self.method,
            adjustment=self.adjustment,
            provenance="fixture",
        )


class FixtureDefinitions(_SpecModel):
    instruments: list[InstrumentSpec]
    futures_contracts: list[FuturesContractSpec] = Field(default_factory=list)
    roll_maps: list[RollSpec] = Field(default_factory=list)

    def contracts_for(self, root: str) -> list[FuturesContractSpec]:
        return [c for c in self.futures_contracts if c.root == root]


class FixtureInputs(_SpecModel):
    """Everything the generator reads, plus a hash of it for ``data_revision``."""

    definitions: FixtureDefinitions
    calendars: dict[str, SessionCalendar]
    inputs_hash: str

    def calendar_for(self, calendar_id: str) -> SessionCalendar:
        try:
            return self.calendars[calendar_id]
        except KeyError as exc:
            msg = f"unknown session calendar {calendar_id!r}"
            raise KeyError(msg) from exc


def _read_yaml(path: Path) -> object:
    with path.open("rb") as handle:
        return yaml.safe_load(handle)


def load_fixture_inputs(fixtures_dir: Path = DEFAULT_FIXTURES_DIR) -> FixtureInputs:
    contracts_path = fixtures_dir / "contracts" / "instruments.yaml"
    calendar_paths = sorted((fixtures_dir / "session_calendars").glob("*.yaml"))
    if not contracts_path.is_file():
        msg = f"missing fixture definitions: {contracts_path}"
        raise FileNotFoundError(msg)
    if not calendar_paths:
        msg = f"no session calendars under {fixtures_dir / 'session_calendars'}"
        raise FileNotFoundError(msg)

    digest = hashlib.sha256()
    for path in [contracts_path, *calendar_paths]:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())

    definitions = FixtureDefinitions.model_validate(_read_yaml(contracts_path))
    calendars = {
        cal.id: cal
        for cal in (SessionCalendar.model_validate(_read_yaml(p)) for p in calendar_paths)
    }
    for spec in definitions.instruments:
        if spec.session_calendar_id not in calendars:
            msg = f"{spec.symbol}: unknown session calendar {spec.session_calendar_id!r}"
            raise ValueError(msg)
    roots = {spec.symbol for spec in definitions.instruments}
    for contract in definitions.futures_contracts:
        if contract.root not in roots:
            msg = f"{contract.contract_code}: root {contract.root!r} is not a defined instrument"
            raise ValueError(msg)
    return FixtureInputs(
        definitions=definitions, calendars=calendars, inputs_hash=digest.hexdigest()
    )
