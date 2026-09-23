"""API boots in fixture mode and serves /health, /openapi.json and fixture market data."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trading_api.main import create_app
from trading_api.settings import ApiSettings


@pytest.fixture
def client(generated_dir: Path) -> Iterator[TestClient]:
    settings = ApiSettings(mode="fixture", fixtures_root=generated_dir, supabase_jwt_secret="")
    with TestClient(create_app(settings)) as http:
        yield http


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mode"] == "fixture" and body["provenance"] == "fixture"
    assert body["fixtures_loaded"] is True
    assert body["data_revision"].startswith("fixture-")
    assert body["order_write_capability"] is False


def test_openapi_publishes_every_shared_contract(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]
    for name in (
        "Instrument",
        "FuturesContract",
        "Bar",
        "Trade",
        "TAFeature",
        "TAEvent",
        "Thesis",
        "Job",
        "Run",
        "ModelResponse",
    ):
        assert name in schemas, name
    assert schemas["Bar"]["properties"]["open"] == {
        "type": "string",
        "format": "decimal",
        "title": "Open",
        "description": "Exact decimal encoded as a string (money, prices, sizes).",
    }


def test_fixture_market_routes(client: TestClient) -> None:
    contracts = client.get("/v1/futures-contracts", params={"root": "CL"})
    assert contracts.status_code == 200
    [clx6] = contracts.json()
    assert clx6["contract_code"] == "CLX6" and clx6["tick_value"] == "10.00"

    bars = client.get("/v1/bars", params={"symbol": "CLX6", "limit": 3})
    assert bars.status_code == 200
    body = bars.json()
    assert body["provenance"] == "fixture" and len(body["bars"]) == 3
    assert body["bars"][0]["origin_time"].endswith("Z")

    missing = client.get("/v1/bars", params={"symbol": "ZZZ9"})
    assert missing.status_code == 404


def test_boots_without_fixtures_and_reports_it(tmp_path: Path) -> None:
    settings = ApiSettings(mode="fixture", fixtures_root=tmp_path / "missing")
    with TestClient(create_app(settings)) as http:
        health = http.get("/health")
        assert health.status_code == 200 and health.json()["fixtures_loaded"] is False
        assert http.get("/openapi.json").status_code == 200
        assert http.get("/v1/instruments").status_code == 503


def test_live_mode_refuses_unauthenticated_requests(generated_dir: Path) -> None:
    settings = ApiSettings(mode="live", fixtures_root=generated_dir, supabase_jwt_secret="x")
    with TestClient(create_app(settings)) as http:
        assert http.get("/health").status_code == 200
        assert http.get("/v1/instruments").status_code == 401
        with_token = http.get("/v1/instruments", headers={"Authorization": "Bearer t"})
        assert with_token.status_code == 501
