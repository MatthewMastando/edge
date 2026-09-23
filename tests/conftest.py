from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from trading_core.data.fixture import FixtureAdapter
from trading_core.fixtures.generator import generate_fixtures
from trading_core.fixtures.manifest import FixtureManifest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "fixtures"

TEST_SEED = 7
TEST_SESSION_DAYS = 2
TEST_START = date(2026, 8, 31)


@pytest.fixture(scope="session")
def generated_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("fixtures")
    generate_fixtures(
        output_dir=out,
        fixtures_dir=FIXTURES_DIR,
        seed=TEST_SEED,
        start=TEST_START,
        session_days=TEST_SESSION_DAYS,
    )
    return out


@pytest.fixture(scope="session")
def manifest(generated_dir: Path) -> FixtureManifest:
    return FixtureAdapter(generated_dir).manifest


@pytest.fixture(scope="session")
def adapter(generated_dir: Path) -> FixtureAdapter:
    return FixtureAdapter(generated_dir)


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("DATABASE_ADMIN_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("set DATABASE_URL to a disposable Postgres to run migration smoke tests")
    return url
