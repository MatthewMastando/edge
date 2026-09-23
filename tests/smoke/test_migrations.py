"""Migrations apply on a fresh Postgres and the schema enforces the documented invariants.

Runs when DATABASE_URL (or DATABASE_ADMIN_URL) points at a disposable Postgres with permission to
create databases: `supabase start` locally, a `postgres` service container in CI.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import errors

from tests.conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from apply_migrations import apply_migrations, migration_files

pytestmark = pytest.mark.postgres

EXPECTED_TABLES = {
    "instruments",
    "futures_contracts",
    "roll_maps",
    "session_calendars",
    "watchlists",
    "watchlist_items",
    "market_snapshots",
    "ta_features",
    "ta_events",
    "ta_feature_transitions",
    "sources",
    "source_excerpts",
    "conversations",
    "messages",
    "artifacts",
    "artifact_revisions",
    "artifact_drafts",
    "artifact_proposed_edits",
    "routines",
    "jobs",
    "runs",
    "run_events",
    "tool_calls",
    "notifications",
    "hypotheses",
    "hypothesis_observations",
    "import_batches",
    "imported_fills",
    "account_snapshots",
    "usage_ledger",
    "budgets",
    "settings",
}


@pytest.fixture(scope="module")
def fresh_database(database_url: str) -> Iterator[str]:
    name = f"trw_smoke_{uuid.uuid4().hex[:12]}"
    admin = psycopg.connect(database_url, autocommit=True)
    admin.execute(f'create database "{name}"')
    target = psycopg.conninfo.make_conninfo(database_url, dbname=name)
    try:
        yield target
    finally:
        admin.execute(f'drop database "{name}" with (force)')
        admin.close()


@pytest.fixture(scope="module")
def migrated(fresh_database: str) -> str:
    applied = apply_migrations(fresh_database, seed=True, quiet=True)
    assert len(applied) == len(migration_files())
    assert apply_migrations(fresh_database, quiet=True) == [], "re-running must be a no-op"
    return fresh_database


def test_all_core_tables_exist(migrated: str) -> None:
    with psycopg.connect(migrated) as conn:
        rows = conn.execute(
            "select table_name from information_schema.tables where table_schema = 'public'"
        ).fetchall()
    tables = {row[0] for row in rows}
    assert tables >= EXPECTED_TABLES
    assert "schema_migrations" in tables


def test_timestamps_are_timestamptz_and_money_is_numeric(migrated: str) -> None:
    with psycopg.connect(migrated) as conn:
        rows = conn.execute(
            """
            select table_name, column_name, data_type
            from information_schema.columns
            where table_schema = 'public'
              and (column_name like '%_at' or column_name like '%_time'
                   or column_name in ('as_of', 'lease_until', 'scheduled_for', 'range_start', 'range_end'))
            """
        ).fetchall()
        bad = [r for r in rows if r[2] != "timestamp with time zone"]
        assert bad == [], bad

        floats = conn.execute(
            """
            select table_name, column_name, data_type from information_schema.columns
            where table_schema = 'public' and data_type in ('real', 'double precision')
            """
        ).fetchall()
        assert floats == [], "prices and money must be numeric"

        for column in ("tick_size", "tick_value", "multiplier"):
            (kind,) = conn.execute(
                "select data_type from information_schema.columns "
                "where table_name = 'instruments' and column_name = %s",
                (column,),
            ).fetchone()  # type: ignore[misc]
            assert kind == "numeric"

        (tz_cols,) = conn.execute(
            "select count(*) from information_schema.columns "
            "where table_schema = 'public' and column_name in ('origin_tz', 'as_of_tz', 'event_tz', 'fill_tz', 'scheduled_tz')"
        ).fetchone()  # type: ignore[misc]
        assert tz_cols >= 5


def test_jobs_state_machine_is_enforced(migrated: str) -> None:
    with psycopg.connect(migrated, autocommit=True) as conn:
        (job_id,) = conn.execute(
            "insert into jobs (kind, idempotency_key) values ('research', %s) returning id",
            (f"k-{uuid.uuid4()}",),
        ).fetchone()  # type: ignore[misc]

        with pytest.raises(errors.CheckViolation):
            conn.execute("update jobs set state = 'completed' where id = %s", (job_id,))

        with pytest.raises(errors.CheckViolation):  # running requires a lease
            conn.execute("update jobs set state = 'running' where id = %s", (job_id,))

        conn.execute(
            "update jobs set state = 'running', lease_until = now() + interval '60 seconds', "
            "leased_by = 'w1' where id = %s",
            (job_id,),
        )
        conn.execute("update jobs set state = 'queued' where id = %s", (job_id,))  # lease expiry
        (attempts, leased_by) = conn.execute(
            "select attempts, leased_by from jobs where id = %s", (job_id,)
        ).fetchone()  # type: ignore[misc]
        assert attempts == 1 and leased_by is None

        conn.execute(
            "update jobs set state = 'running', lease_until = now() + interval '60 seconds' where id = %s",
            (job_id,),
        )
        conn.execute("update jobs set state = 'partial' where id = %s", (job_id,))
        conn.execute("update jobs set state = 'budget_exceeded' where id = %s", (job_id,))
        with pytest.raises(errors.CheckViolation):
            conn.execute("update jobs set state = 'queued' where id = %s", (job_id,))

        with pytest.raises(errors.UniqueViolation):
            conn.execute(
                "insert into jobs (kind, idempotency_key) values ('research', "
                "(select idempotency_key from jobs where id = %s))",
                (job_id,),
            )


def test_ta_events_are_idempotent_per_revision(migrated: str) -> None:
    with psycopg.connect(migrated, autocommit=True) as conn:
        (instrument_id,) = conn.execute(
            """
            insert into instruments (symbol, name, asset_class, venue, currency, tick_size, tick_value,
                                     multiplier, session_calendar_id, provenance)
            values (%s, 'Euro FX', 'futures', 'CME', 'USD', 0.00005, 6.25, 125000, 'cme_globex_fx', 'fixture')
            returning id
            """,
            (f"6E-{uuid.uuid4().hex[:6]}",),
        ).fetchone()  # type: ignore[misc]
        (snapshot_id,) = conn.execute(
            """
            insert into market_snapshots (instrument_id, contract_code, timeframe, kind, range_start, range_end,
                                          as_of, provider, provenance, data_revision, storage_backend, storage_key,
                                          row_count, content_hash)
            values (%s, '6EZ6', '5m', 'bars', now() - interval '1 day', now(), now(), 'fixture', 'fixture',
                    'rev-1', 'local', %s, 10, repeat('a', 64))
            returning id
            """,
            (instrument_id, f"bars/{uuid.uuid4().hex}.parquet"),
        ).fetchone()  # type: ignore[misc]
        (feature_id,) = conn.execute(
            """
            insert into ta_features (detector, calc_version, instrument_id, contract_code, timeframe, session,
                                     session_calendar_id, session_calendar_version, direction, state, origin_time,
                                     origin_tz, confirmation_time, as_of, snapshot_id, data_revision, provenance)
            values ('fvg', '1.0.0', %s, '6EZ6', '5m', 'current_session', 'cme_globex_fx', '1.0.0', 'bullish',
                    'confirmed', '2026-08-31 22:15+00', 'America/Chicago', '2026-08-31 22:25+00',
                    '2026-08-31 22:25+00', %s, 'rev-1', 'fixture')
            returning id
            """,
            (instrument_id, snapshot_id),
        ).fetchone()  # type: ignore[misc]

        insert_event = """
            insert into ta_events (feature_id, instrument_id, contract_code, timeframe, detector, calc_version,
                                   origin_time, data_revision, event_time, event_tz, direction, provenance)
            values (%s, %s, '6EZ6', '5m', 'fvg', '1.0.0', '2026-08-31 22:15+00', %s,
                    '2026-08-31 22:25+00', 'America/Chicago', 'bullish', 'fixture')
        """
        conn.execute(insert_event, (feature_id, instrument_id, "rev-1"))
        with pytest.raises(errors.UniqueViolation):
            conn.execute(insert_event, (feature_id, instrument_id, "rev-1"))
        # A new data revision is a new log; it never rewrites the old one.
        conn.execute(insert_event, (feature_id, instrument_id, "rev-2"))


def test_tool_calls_reject_order_write_tool_names(migrated: str) -> None:
    with psycopg.connect(migrated, autocommit=True) as conn:
        run_id = _make_run(conn)
        conn.execute(
            "insert into tool_calls (run_id, sequence, tool_name, tool_version) "
            "values (%s, 0, 'get_bars', '1.0.0')",
            (run_id,),
        )
        for forbidden in ("submit_order", "cancelOrder", "run_shell", "http_request"):
            with pytest.raises(errors.CheckViolation):
                conn.execute(
                    "insert into tool_calls (run_id, sequence, tool_name, tool_version) "
                    "values (%s, 1, %s, '1.0.0')",
                    (run_id, forbidden),
                )


def _make_run(conn: psycopg.Connection) -> uuid.UUID:
    (job_id,) = conn.execute(
        "insert into jobs (kind, idempotency_key) values ('research', %s) returning id",
        (f"run-{uuid.uuid4()}",),
    ).fetchone()  # type: ignore[misc]
    (run_id,) = conn.execute(
        "insert into runs (job_id, provider, provenance) values (%s, 'recorded', 'recorded') returning id",
        (job_id,),
    ).fetchone()  # type: ignore[misc]
    return run_id  # type: ignore[no-any-return]


def test_migration_files_are_ordered_and_named(migrated: str) -> None:
    names = [p.name for p in migration_files()]
    assert names == sorted(names)
    assert all(Path(n).suffix == ".sql" and n[:14].isdigit() for n in names)
