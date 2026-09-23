"""Versioned session calendars and contract metadata. Prices never come from this book."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from trading_core.fixtures.spec import FuturesContractSpec, InstrumentSpec, load_fixture_inputs

if TYPE_CHECKING:
    from pathlib import Path

    from trading_core.domain.instruments import SessionCalendar


@dataclass(frozen=True)
class ReferenceBook:
    """Calendar and settlement metadata shipped with the repo (plan hole 3)."""

    instruments: dict[str, InstrumentSpec]
    contracts: dict[str, FuturesContractSpec]
    calendars: dict[str, SessionCalendar]

    @classmethod
    def load(cls, fixtures_dir: Path) -> ReferenceBook:
        inputs = load_fixture_inputs(fixtures_dir)
        return cls(
            instruments={item.symbol: item for item in inputs.definitions.instruments},
            contracts={item.contract_code: item for item in inputs.definitions.futures_contracts},
            calendars=dict(inputs.calendars),
        )

    def calendar(self, calendar_id: str) -> SessionCalendar:
        try:
            return self.calendars[calendar_id]
        except KeyError as exc:
            msg = f"unknown session calendar {calendar_id}"
            raise KeyError(msg) from exc

    def instrument(self, symbol: str) -> InstrumentSpec | None:
        return self.instruments.get(symbol)

    def contract(self, code: str) -> FuturesContractSpec | None:
        return self.contracts.get(code)
