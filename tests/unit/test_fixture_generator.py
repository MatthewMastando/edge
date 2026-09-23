from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq

from tests.conftest import FIXTURES_DIR, TEST_SEED, TEST_SESSION_DAYS, TEST_START
from trading_core.fixtures.generator import generate_fixtures, verify_fixtures
from trading_core.fixtures.manifest import FixtureManifest
from trading_core.storage.schemas import table_to_bars, table_to_trades


def test_manifest_labels_everything_as_fixture(manifest: FixtureManifest) -> None:
    assert manifest.label.provenance == "fixture"
    assert re.fullmatch(r"fixture-\d+\.\d+\.\d+-s7-[0-9a-f]{8}", manifest.data_revision)
    assert all(i.provenance == "fixture" for i in manifest.instruments)
    assert all(c.provenance == "fixture" for c in manifest.futures_contracts)
    assert all(s.provenance == "fixture" and s.provider == "fixture" for s in manifest.snapshots)
    assert len(manifest.snapshots) == 12  # 6 symbols x (bars, trades)


def test_contract_metadata_matches_listed_specifications(manifest: FixtureManifest) -> None:
    by_code = {c.contract_code: c for c in manifest.futures_contracts}
    assert set(by_code) == {"6EZ6", "GCZ6", "CLX6", "ESZ6"}

    euro = by_code["6EZ6"]
    assert (euro.exchange, euro.tick_size, euro.tick_value) == (
        "CME",
        Decimal("0.00005"),
        Decimal("6.25"),
    )
    assert euro.point_multiplier == Decimal(125000)
    assert euro.settlement_type == "physical"
    assert euro.expiry_date.isoformat() == "2026-12-16"

    gold = by_code["GCZ6"]
    assert gold.first_notice_date is not None and gold.first_notice_date.isoformat() == "2026-11-30"
    assert gold.tick_value / gold.tick_size == gold.point_multiplier

    es = by_code["ESZ6"]
    assert es.settlement_type == "cash" and es.first_notice_date is None
    assert es.tick_size * es.point_multiplier == es.tick_value

    for contract in by_code.values():
        assert contract.expiry_date >= contract.last_trade_date
        assert contract.contract_month.startswith("2026-")


def test_bars_are_consistent_with_trades_and_tick_aligned(
    generated_dir: Path, manifest: FixtureManifest
) -> None:
    contract = next(c for c in manifest.futures_contracts if c.contract_code == "GCZ6")
    bars = table_to_bars(pq.read_table(generated_dir / "bars" / "GCZ6" / "5m.parquet"))
    trades = table_to_trades(pq.read_table(generated_dir / "trades" / "GCZ6.parquet"))

    assert len(bars) == TEST_SESSION_DAYS * 276
    assert all(b.contract_code == "GCZ6" and b.provenance == "fixture" for b in bars)
    assert [t.sequence for t in trades] == list(range(len(trades)))
    assert all(trades[i].trade_time <= trades[i + 1].trade_time for i in range(len(trades) - 1))

    by_bar: dict[object, list[Decimal]] = {}
    volume: dict[object, Decimal] = {}
    for trade in trades:
        assert trade.price % contract.tick_size == 0
        assert trade.side == "unknown", "aggressor side is not claimed for futures prints"
        key = trade.trade_time.replace(
            minute=trade.trade_time.minute - trade.trade_time.minute % 5, second=0, microsecond=0
        )
        by_bar.setdefault(key, []).append(trade.price)
        volume[key] = volume.get(key, Decimal(0)) + trade.size

    for bar in bars:
        prices = by_bar[bar.origin_time]
        assert bar.open == prices[0] and bar.close == prices[-1]
        assert bar.high == max(prices) and bar.low == min(prices)
        assert bar.volume == volume[bar.origin_time]
        assert bar.trade_count == len(prices)
        assert bar.low <= bar.vwap <= bar.high  # type: ignore[operator]


def test_crypto_sizes_are_fractional_and_sided(generated_dir: Path) -> None:
    trades = table_to_trades(pq.read_table(generated_dir / "trades" / "BTC-USD.parquet"))
    assert any(t.size != t.size.to_integral_value() for t in trades)
    assert {t.side for t in trades} <= {"buy", "sell"}
    assert all(t.venue == "COINBASE" for t in trades)


def test_generation_is_deterministic(tmp_path: Path, manifest: FixtureManifest) -> None:
    again = generate_fixtures(
        output_dir=tmp_path,
        fixtures_dir=FIXTURES_DIR,
        seed=TEST_SEED,
        start=TEST_START,
        session_days=TEST_SESSION_DAYS,
    )
    assert again.data_revision == manifest.data_revision
    assert [s.content_hash for s in again.snapshots] == [s.content_hash for s in manifest.snapshots]
    assert verify_fixtures(tmp_path) == []


def test_different_seed_changes_data_and_revision(
    tmp_path: Path, manifest: FixtureManifest
) -> None:
    other = generate_fixtures(
        output_dir=tmp_path,
        fixtures_dir=FIXTURES_DIR,
        seed=TEST_SEED + 1,
        start=TEST_START,
        session_days=TEST_SESSION_DAYS,
    )
    assert other.data_revision != manifest.data_revision
    assert other.snapshots[0].content_hash != manifest.snapshots[0].content_hash


def test_parquet_files_carry_fixture_metadata(generated_dir: Path) -> None:
    for path in generated_dir.rglob("*.parquet"):
        metadata = pq.read_schema(path).metadata or {}
        assert metadata[b"trw.provenance"] == b"fixture"
        assert b"trw.data_revision" in metadata
