"""Deterministic fixture generation. See ``fixtures/README.md`` at the repository root."""

from trading_core.fixtures.generator import (
    DEFAULT_SEED,
    DEFAULT_SESSION_DAYS,
    DEFAULT_START_DATE,
    GENERATOR_VERSION,
    bars_key,
    generate_fixtures,
    trades_key,
    verify_fixtures,
)
from trading_core.fixtures.manifest import MANIFEST_FILENAME, FixtureManifest, read_manifest
from trading_core.fixtures.spec import FixtureInputs, fixture_uuid, load_fixture_inputs

__all__ = [
    "DEFAULT_SEED",
    "DEFAULT_SESSION_DAYS",
    "DEFAULT_START_DATE",
    "GENERATOR_VERSION",
    "MANIFEST_FILENAME",
    "FixtureInputs",
    "FixtureManifest",
    "bars_key",
    "fixture_uuid",
    "generate_fixtures",
    "load_fixture_inputs",
    "read_manifest",
    "trades_key",
    "verify_fixtures",
]
