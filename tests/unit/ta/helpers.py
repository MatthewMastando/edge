"""Bar and calendar builders for TA tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import JsonValue

from trading_core.domain.common import SessionScope, Timeframe
from trading_core.domain.instruments import Instrument, SessionCalendar, SessionWindow, Weekday
from trading_core.domain.market import Bar, BarSeries, Trade, TradeBatch
from trading_core.ta.interfaces import DetectorInput

INSTRUMENT_ID = UUID("11111111-1111-4111-8111-111111111111")
SNAPSHOT_ID = UUID("22222222-2222-4222-8222-222222222222")
REVISION = "ta-rev-1"

_ALL_DAYS: list[Weekday] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_WEEKDAYS: list[Weekday] = ["mon", "tue", "wed", "thu", "fri"]


def instrument(tick: str = "1", symbol: str = "TEST") -> Instrument:
    size = Decimal(tick)
    return Instrument(
        id=INSTRUMENT_ID,
        symbol=symbol,
        name="Test instrument",
        asset_class="futures",
        venue="CME",
        currency="USD",
        tick_size=size,
        tick_value=size,
        multiplier=Decimal(1),
        session_calendar_id="test",
    )


def crypto_calendar() -> SessionCalendar:
    return SessionCalendar(
        id="crypto_24x7",
        name="crypto",
        version="1.0.0",
        timezone="UTC",
        trading_days=list(_ALL_DAYS),
        windows=[
            SessionWindow(
                name="utc_day", open_time=time(0, 0), close_time=time(0, 0), kind="trading"
            )
        ],
        holidays=[],
        always_open=True,
    )


def split_calendar() -> SessionCalendar:
    """UTC session 08:00-12:00 with an RTH sub-window 10:00-11:00. Every weekday is open."""
    return SessionCalendar(
        id="test_split",
        name="split",
        version="1.0.0",
        timezone="UTC",
        trading_days=list(_ALL_DAYS),
        windows=[
            SessionWindow(
                name="globex", open_time=time(8, 0), close_time=time(12, 0), kind="trading"
            ),
            SessionWindow(
                name="rth", open_time=time(10, 0), close_time=time(11, 0), kind="sub_session"
            ),
        ],
        holidays=[],
    )


def weekday_calendar() -> SessionCalendar:
    """Two 15-minute bars, 09:00-09:30 UTC, Monday-Friday. Holidays stay empty."""
    return SessionCalendar(
        id="test_weekday",
        name="weekday",
        version="1.0.0",
        timezone="UTC",
        trading_days=list(_WEEKDAYS),
        windows=[
            SessionWindow(name="rth", open_time=time(9, 0), close_time=time(9, 30), kind="trading")
        ],
        holidays=[],
    )


def short_session_calendar() -> SessionCalendar:
    """15-minute bars, 09:00-10:00 UTC, every day open."""
    return SessionCalendar(
        id="test_short",
        name="short",
        version="1.0.0",
        timezone="UTC",
        trading_days=list(_ALL_DAYS),
        windows=[
            SessionWindow(name="rth", open_time=time(9, 0), close_time=time(10, 0), kind="trading")
        ],
        holidays=[],
    )


def ohlc(
    close: int | str,
    *,
    high: int | str | None = None,
    low: int | str | None = None,
    open_: int | str | None = None,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    closed = Decimal(close)
    opened = closed if open_ is None else Decimal(open_)
    hi = closed if high is None else Decimal(high)
    lo = closed if low is None else Decimal(low)
    return opened, hi, lo, closed


def make_bars(
    candles: list[tuple[Decimal, Decimal, Decimal, Decimal]],
    *,
    start: datetime,
    timeframe: Timeframe = "15m",
    step: timedelta | None = None,
    contract: str | None = "ESZ6",
    contracts: Sequence[str | None] | None = None,
    volume: str = "1",
    origins: list[datetime] | None = None,
) -> list[Bar]:
    width = step if step is not None else _step(timeframe)
    size = Decimal(volume)
    bars: list[Bar] = []
    for index, (opened, high, low, close) in enumerate(candles):
        origin = origins[index] if origins is not None else start + (width * index)
        code = contract if contracts is None else contracts[index]
        bars.append(
            Bar(
                instrument_id=INSTRUMENT_ID,
                contract_code=code,
                timeframe=timeframe,
                origin_time=origin,
                origin_tz="UTC",
                open=opened,
                high=high,
                low=low,
                close=close,
                volume=size,
                is_complete=True,
                data_revision=REVISION,
                provenance="fixture",
            )
        )
    return bars


def make_trades(
    prints: list[tuple[datetime, str, str]],
    *,
    contract: str | None = "ESZ6",
) -> TradeBatch:
    trades = [
        Trade(
            instrument_id=INSTRUMENT_ID,
            contract_code=contract,
            sequence=index,
            trade_time=instant,
            trade_tz="UTC",
            price=Decimal(price),
            size=Decimal(size),
            side="unknown",
            venue="fixture",
            data_revision=REVISION,
            provenance="fixture",
        )
        for index, (instant, price, size) in enumerate(prints)
    ]
    return TradeBatch(
        instrument_id=INSTRUMENT_ID,
        contract_code=contract,
        data_revision=REVISION,
        provenance="fixture",
        trades=trades,
    )


def detector_input(
    bars: list[Bar],
    calendar: SessionCalendar,
    *,
    session: SessionScope = "current_session",
    trades: TradeBatch | None = None,
    parameters: dict[str, JsonValue] | None = None,
    tick: str = "1",
) -> DetectorInput:
    assert bars
    series = BarSeries(
        instrument_id=INSTRUMENT_ID,
        contract_code=bars[0].contract_code,
        timeframe=bars[0].timeframe,
        data_revision=REVISION,
        provenance="fixture",
        bars=bars,
    )
    params: dict[str, JsonValue] = {} if parameters is None else parameters
    return DetectorInput(
        instrument=instrument(tick),
        calendar=calendar,
        session=session,
        bars=series,
        trades=trades,
        snapshot_id=SNAPSHOT_ID,
        parameters=params,
    )


def _step(timeframe: Timeframe) -> timedelta:
    seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14_400, "1d": 86_400}
    return timedelta(seconds=seconds[timeframe])


def other_rows(bars: list[Bar], closes: list[str] | None = None) -> list[JsonValue]:
    rows: list[JsonValue] = []
    for index, bar in enumerate(bars):
        close = format(bar.close, "f") if closes is None else closes[index]
        row: dict[str, JsonValue] = {
            "origin_time": bar.origin_time.isoformat(),
            "close": close,
        }
        rows.append(row)
    return rows


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)
