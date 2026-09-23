from __future__ import annotations

from datetime import UTC, date, datetime

from tests.conftest import FIXTURES_DIR
from trading_core.fixtures.sessions import bar_origins, session_dates
from trading_core.fixtures.spec import load_fixture_inputs


def test_globex_session_opens_the_prior_evening_and_skips_the_break() -> None:
    inputs = load_fixture_inputs(FIXTURES_DIR)
    calendar = inputs.calendar_for("cme_globex_fx")
    origins = [ts for _, ts in bar_origins(calendar, date(2026, 8, 31), 2, 300)]

    assert origins[0] == datetime(2026, 8, 30, 22, 0, tzinfo=UTC)  # Sunday 17:00 CDT
    assert len(origins) == 2 * 276  # 23 hours of 5-minute bars per session
    # Monday 16:00-17:00 CT (21:00-22:00 UTC) has no bars.
    assert datetime(2026, 8, 31, 21, 0, tzinfo=UTC) not in origins
    assert datetime(2026, 8, 31, 22, 0, tzinfo=UTC) in origins


def test_equity_rth_and_crypto_sessions() -> None:
    inputs = load_fixture_inputs(FIXTURES_DIR)
    rth = [
        ts for _, ts in bar_origins(inputs.calendar_for("us_equity_rth"), date(2026, 8, 31), 1, 300)
    ]
    assert len(rth) == 78
    assert rth[0] == datetime(2026, 8, 31, 13, 30, tzinfo=UTC)  # 09:30 EDT

    crypto = bar_origins(inputs.calendar_for("crypto_24x7"), date(2026, 8, 29), 2, 300)
    assert len(crypto) == 2 * 288
    assert crypto[0][0] == date(2026, 8, 29)  # Saturday is a session for crypto


def test_session_dates_skip_weekends() -> None:
    inputs = load_fixture_inputs(FIXTURES_DIR)
    days = session_dates(inputs.calendar_for("cme_globex_fx"), date(2026, 9, 4), 3)
    assert days == [date(2026, 9, 4), date(2026, 9, 7), date(2026, 9, 8)]
