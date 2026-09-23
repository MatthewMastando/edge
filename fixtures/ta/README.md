# Hand-calculated TA expectations (calc version 1.0.0)

These files are the reference numbers for `trading_core.ta`. Tests recompute the same
cases with an independent oracle and compare both to the library.

- `wilder.json` — RSI(14) and ATR(14) seed-and-smooth values, including the 100/0/50 cases.
- `volume_profile.json` — POC, value area and node percentiles for one 15-bin histogram.

Holiday lists in `session_calendars/` stay empty. A weekday such as US Labor Day 2026-09-07
is a trading day until a holiday list is supplied. This package does not call
`exchange_calendars`.
