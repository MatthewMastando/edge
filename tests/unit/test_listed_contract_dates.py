"""Listed fixture dates follow published CME termination and notice rules.

Rules encoded here (business day = weekday that is not a full-day CME closure; early closes
still count):

- 6E: delivery on the third Wednesday; last trade is two business days earlier, 09:16 CT.
- GC: last trade 12:30 CT on the third-last business day of the delivery month; first notice
  is the last business day of the preceding month.
- CL: last trade 13:30 CT on the third business day before the 25th of the month prior to
  delivery, or before the last business day preceding the 25th when that day is closed.
  There is no separate first notice day.
- ES: last trade 08:30 CT on the third Friday; daily settlement is the 15:14:30-15:15:00 CT VWAP.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from tests.conftest import FIXTURES_DIR
from trading_core.fixtures.spec import load_fixture_inputs

# Full-day CME Group closures in 2026. Early-close sessions are not in this set.
_CME_HOLIDAYS_2026 = {
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 4, 3),
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
}


def _is_business_day(day: date) -> bool:
    return day.weekday() < 5 and day not in _CME_HOLIDAYS_2026


def _shift_business_days(day: date, steps: int) -> date:
    step = 1 if steps > 0 else -1
    remaining = abs(steps)
    cursor = day
    while remaining:
        cursor += timedelta(days=step)
        if _is_business_day(cursor):
            remaining -= 1
    return cursor


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _last_business_day(year: int, month: int) -> date:
    cursor = _month_end(year, month)
    while not _is_business_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def euro_fx_dates(year: int, month: int) -> tuple[date, date]:
    delivery = _nth_weekday(year, month, 2, 3)
    if not _is_business_day(delivery):
        delivery += timedelta(days=1)
        while not _is_business_day(delivery):
            delivery += timedelta(days=1)
    return delivery, _shift_business_days(delivery, -2)


def gold_dates(year: int, month: int) -> tuple[date, date]:
    prior_month = date(year, month, 1) - timedelta(days=1)
    first_notice = _last_business_day(prior_month.year, prior_month.month)
    last_trade = _shift_business_days(_last_business_day(year, month), -2)
    return last_trade, first_notice


def crude_last_trade(delivery_year: int, delivery_month: int) -> date:
    prior = date(delivery_year, delivery_month, 1) - timedelta(days=1)
    twenty_fifth = date(prior.year, prior.month, 25)
    anchor = twenty_fifth
    while not _is_business_day(anchor):
        anchor -= timedelta(days=1)
    return _shift_business_days(anchor, -3)


def equity_index_last_trade(year: int, month: int) -> date:
    friday = _nth_weekday(year, month, 4, 3)
    while not _is_business_day(friday):
        friday -= timedelta(days=1)
    return friday


def test_fixture_contracts_match_published_cme_rules() -> None:
    contracts = {
        contract.contract_code: contract
        for contract in load_fixture_inputs(FIXTURES_DIR).definitions.futures_contracts
    }
    euro_expiry, euro_last = euro_fx_dates(2026, 12)
    euro = contracts["6EZ6"]
    assert (euro.expiry_date, euro.last_trade_date) == (euro_expiry, euro_last)
    assert euro.last_trade_date.isoformat() == "2026-12-14"
    assert euro.expiry_date.isoformat() == "2026-12-16"
    assert euro.last_trade_time_local == time(9, 16)
    assert euro.first_notice_date is None

    gold_last, gold_notice = gold_dates(2026, 12)
    gold = contracts["GCZ6"]
    assert (gold.last_trade_date, gold.expiry_date) == (gold_last, gold_last)
    assert gold.last_trade_date.isoformat() == "2026-12-29"
    assert gold.first_notice_date == gold_notice
    assert gold.first_notice_date is not None
    assert gold.first_notice_date.isoformat() == "2026-11-30"
    assert gold.last_trade_time_local == time(12, 30)

    crude = contracts["CLX6"]
    assert crude.last_trade_date == crude_last_trade(2026, 11)
    assert crude.last_trade_date.isoformat() == "2026-10-20"
    assert crude.expiry_date == crude.last_trade_date
    assert crude.last_trade_time_local == time(13, 30)
    assert crude.first_notice_date is None

    es = contracts["ESZ6"]
    assert es.last_trade_date == equity_index_last_trade(2026, 12)
    assert es.last_trade_date.isoformat() == "2026-12-18"
    assert es.expiry_date == es.last_trade_date
    assert es.last_trade_time_local == time(8, 30)
    assert es.settlement_time_local == time(15, 15)
    assert es.first_notice_date is None
    assert es.settlement_type == "cash"

    # The September roll examples sit on the prior contracts' real last-trade dates.
    assert euro_fx_dates(2026, 9)[1].isoformat() == "2026-09-14"
    assert equity_index_last_trade(2026, 9).isoformat() == "2026-09-18"


def test_equity_index_settlement_window_is_the_1515_vwap() -> None:
    calendar = load_fixture_inputs(FIXTURES_DIR).calendar_for("cme_globex_equity_index")
    settlement = next(window for window in calendar.windows if window.name == "settlement")
    assert settlement.open_time == time(15, 14, 30)
    assert settlement.close_time == time(15, 15)
    assert calendar.version == "1.0.1"
