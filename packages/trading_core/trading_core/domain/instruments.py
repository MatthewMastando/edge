"""Instruments, listed futures contracts, roll maps and session calendars (spec section 4)."""

from __future__ import annotations

from datetime import date, time
from typing import Literal
from uuid import UUID

from pydantic import Field

from trading_core.domain.common import (
    AssetClass,
    DecimalStr,
    DomainModel,
    Provenance,
    TimezoneName,
)

SettlementType = Literal["cash", "physical"]
RollMethod = Literal["none", "back_adjust_difference", "back_adjust_ratio", "calendar"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Instrument(DomainModel):
    """A tradable or researchable symbol. Futures roots and continuous series are instruments;
    individual listed contracts are :class:`FuturesContract` rows that point back here."""

    id: UUID
    symbol: str = Field(min_length=1, max_length=32, examples=["6E", "SPY", "BTC-USD"])
    name: str = Field(min_length=1, max_length=128)
    asset_class: AssetClass
    venue: str = Field(
        min_length=1,
        max_length=32,
        description="Exchange or venue code, e.g. CME, COMEX, NYMEX, ARCA, COINBASE.",
    )
    currency: str = Field(min_length=3, max_length=8, examples=["USD"])
    tick_size: DecimalStr = Field(description="Minimum price increment in quote units.")
    tick_value: DecimalStr = Field(
        description="Cash value of one tick for one unit/contract, in ``currency``."
    )
    multiplier: DecimalStr = Field(
        description="Point multiplier: cash value of a one-point move for one unit/contract."
    )
    session_calendar_id: str = Field(
        min_length=1, max_length=64, description="Key into ``session_calendars``."
    )
    base_asset: str | None = Field(
        default=None, description="Crypto base asset (e.g. BTC) when applicable."
    )
    quote_asset: str | None = Field(
        default=None, description="Crypto quote asset (e.g. USD) when applicable."
    )
    is_continuous: bool = Field(
        default=False,
        description=(
            "True for continuous futures series. Never treat a continuous symbol as a listed "
            "contract; volume profiles are never merged across expiries silently."
        ),
    )
    provenance: Provenance = "live"


class FuturesContract(DomainModel):
    """A listed futures contract with the metadata required by spec section 4."""

    id: UUID
    instrument_id: UUID = Field(description="The root instrument this contract belongs to.")
    root: str = Field(min_length=1, max_length=8, examples=["6E", "GC", "CL", "ES"])
    contract_code: str = Field(min_length=3, max_length=16, examples=["6EZ6", "GCZ6"])
    exchange: str = Field(min_length=1, max_length=32, examples=["CME", "COMEX", "NYMEX"])
    contract_month: str = Field(
        pattern=r"^\d{4}-\d{2}$", description="Delivery month as YYYY-MM.", examples=["2026-12"]
    )
    expiry_date: date = Field(
        description=(
            "Published expiration date for this root. For FX that is the value/delivery date, "
            "which can fall after last trade. For metals, energy and equity index it is the "
            "last trade date, not the end of a physical delivery window."
        )
    )
    last_trade_date: date
    last_trade_time_local: time | None = Field(
        default=None,
        description=(
            "Clock time in the session calendar's timezone when the expiring contract stops "
            "trading. Distinct from the daily settlement time (ES settles at 15:15 CT but "
            "stops trading at 08:30 CT on expiration Friday)."
        ),
    )
    first_notice_date: date | None = Field(
        default=None,
        description="First notice day for physically delivered contracts; null if not applicable.",
    )
    tick_size: DecimalStr
    tick_value: DecimalStr
    point_multiplier: DecimalStr
    currency: str = Field(min_length=3, max_length=8)
    session_calendar_id: str = Field(min_length=1, max_length=64)
    settlement_type: SettlementType
    settlement_time_local: time | None = Field(
        default=None, description="Daily settlement time in the calendar's timezone."
    )
    is_active: bool = True
    provenance: Provenance = "live"


class RollMapEntry(DomainModel):
    """How a continuous series moved from one listed contract to the next."""

    id: UUID
    instrument_id: UUID = Field(description="Continuous-series instrument this roll belongs to.")
    root: str
    from_contract_code: str
    to_contract_code: str
    roll_date: date
    method: RollMethod
    adjustment: DecimalStr | None = Field(
        default=None,
        description="Additive difference or multiplicative ratio applied to prior history.",
    )
    provenance: Provenance = "live"


class SessionWindow(DomainModel):
    """One trading window inside a session day, in the calendar's local timezone."""

    name: str = Field(examples=["globex", "rth", "maintenance_break", "settlement"])
    open_time: time
    close_time: time
    opens_previous_day: bool = Field(
        default=False,
        description="True when the window opens on the calendar day before the session date "
        "(e.g. Globex opens 17:00 CT the prior evening).",
    )
    kind: Literal["trading", "sub_session", "break", "settlement_window"] = Field(
        default="trading",
        description="'trading' windows produce bars; 'sub_session' windows (e.g. RTH inside "
        "Globex) only define session levels.",
    )


class SessionCalendar(DomainModel):
    """Versioned session definition referenced by every feature and snapshot."""

    id: str = Field(min_length=1, max_length=64, examples=["cme_globex_fx", "us_equity_rth"])
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    timezone: TimezoneName
    trading_days: list[Weekday]
    windows: list[SessionWindow]
    exchange_calendar_code: str | None = Field(
        default=None,
        description="exchange_calendars code for holidays (e.g. CMES, XNYS); null for 24/7 venues.",
    )
    holidays: list[date] = Field(default_factory=list)
    always_open: bool = Field(
        default=False, description="True for 24/7 venues such as spot crypto."
    )
    notes: str | None = None
