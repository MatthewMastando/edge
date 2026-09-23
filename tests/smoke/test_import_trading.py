"""CSV import and My Trading API against Postgres."""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.conftest import FIXTURES_DIR, REPO_ROOT
from trading_api.main import create_app
from trading_api.settings import ApiSettings
from trading_core.data.fixture import FixtureAdapter
from trading_core.storage.db import Database
from trading_core.storage.repositories import reference

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from apply_migrations import apply_migrations

pytestmark = pytest.mark.postgres

SAMPLE_CSV = (FIXTURES_DIR / "trading" / "sample-fills.csv").read_text(encoding="utf-8")


def _postgres_url(conninfo: str) -> str:
    params = psycopg.conninfo.conninfo_to_dict(conninfo)
    user = params.get("user") or "postgres"
    password = params.get("password") or ""
    host = params.get("host") or "127.0.0.1"
    port = params.get("port") or 5432
    dbname = params.get("dbname") or "postgres"
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture(scope="module")
def import_db(database_url: str) -> Iterator[str]:
    name = f"trw_import_{uuid.uuid4().hex[:12]}"
    admin = psycopg.connect(database_url, autocommit=True)
    admin.execute(f'create database "{name}"')
    target = psycopg.conninfo.make_conninfo(database_url, dbname=name)
    apply_migrations(target, seed=True, quiet=True)
    try:
        yield _postgres_url(target)
    finally:
        admin.execute(f'drop database "{name}" with (force)')
        admin.close()


@pytest.fixture
def api_client(import_db: str, generated_dir: Path) -> Iterator[TestClient]:
    settings = ApiSettings(
        database_url=import_db,
        mode="fixture",
        fixtures_root=generated_dir,
        cors_origins="http://localhost:5173",
        supabase_jwt_secret="",
    )
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def seeded_instruments(import_db: str, generated_dir: Path) -> None:
    adapter = FixtureAdapter(generated_dir)
    database = Database(import_db)

    async def _seed() -> None:
        async with database.engine.begin() as conn:
            for calendar in adapter.manifest.session_calendars:
                await reference.upsert_session_calendar(conn, calendar)
            for instrument in adapter.manifest.instruments:
                await reference.upsert_instrument(conn, instrument)
            for contract in adapter.manifest.futures_contracts:
                await reference.upsert_futures_contract(conn, contract)

    asyncio.run(_seed())


def test_import_preview_commit_and_reimport(
    api_client: TestClient, seeded_instruments: None
) -> None:
    mapping = {
        "columns": {
            "symbol": "Symbol",
            "side": "Side",
            "quantity": "Quantity",
            "price": "Price",
            "fill_time": "Date",
            "fees": "Fees",
            "contract_code": "Contract",
        },
        "default_currency": "USD",
        "default_fill_tz": "America/New_York",
    }
    preview = api_client.post(
        "/v1/import/preview",
        json={"filename": "sample-fills.csv", "csv_text": SAMPLE_CSV, "mapping": mapping},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["row_count"] == 4
    assert body["duplicate_count"] == 0
    assert body["incomplete_count"] >= 1

    commit = api_client.post(
        "/v1/import/commit",
        json={"filename": "sample-fills.csv", "csv_text": SAMPLE_CSV, "mapping": mapping},
    )
    assert commit.status_code == 200
    result = commit.json()
    assert result["imported_count"] >= 2

    commit2 = api_client.post(
        "/v1/import/commit",
        json={"filename": "sample-fills.csv", "csv_text": SAMPLE_CSV, "mapping": mapping},
    )
    assert commit2.status_code == 200
    assert commit2.json()["duplicate_count"] >= result["imported_count"]

    fills = api_client.get("/v1/trading/fills")
    assert fills.status_code == 200
    fill_rows = fills.json()
    assert len(fill_rows) >= 3
    assert any(row["is_complete"] is False for row in fill_rows)

    summary = api_client.get("/v1/trading/summary")
    assert summary.status_code == 200
    summary_body = summary.json()
    assert summary_body["portfolio_return_available"] is False
    assert summary_body["trusted_fill_count"] == 3
    assert summary_body["incomplete_fill_count"] == 1
    # (1.0865 - 1.0850) * 125000 on 6EZ6. SPY is still open. Fees are not multiplied.
    assert (
        summary_body["total_realized_pnl"] == "187.5000"
        or summary_body["total_realized_pnl"] == "187.5"
    )
    assert summary_body["total_fees"] in {"2.50", "2.5000", "2.5"}

    futures = api_client.get("/v1/trading/fills", params={"asset_class": "futures"})
    assert futures.status_code == 200
    assert {row["symbol_raw"] for row in futures.json()} == {"6E"}
    etf = api_client.get("/v1/trading/summary", params={"asset_class": "etf"})
    assert etf.status_code == 200
    assert etf.json()["trusted_fill_count"] == 1
    assert etf.json()["total_realized_pnl"] in {"0", "0.0", "0.00", "0.0000"}
    missing_family = api_client.get("/v1/trading/summary", params={"asset_class": "fx_futures"})
    assert missing_family.status_code == 200
    assert missing_family.json()["trusted_fill_count"] == 0


def test_kalshi_fixture_brief(api_client: TestClient) -> None:
    markets = api_client.get("/v1/kalshi/markets")
    assert markets.status_code == 200
    tickers = [m["ticker"] for m in markets.json()]
    assert tickers
    brief = api_client.get(f"/v1/kalshi/markets/{tickers[0]}/brief")
    assert brief.status_code == 200
    assert brief.json()["is_demonstration"] is True
