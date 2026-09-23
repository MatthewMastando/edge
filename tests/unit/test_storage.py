from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from trading_core.domain.market import Bar, Trade
from trading_core.storage import (
    LocalParquetStore,
    ObjectNotFoundError,
    ObjectStore,
    StorageKeyError,
    SupabaseStorageStore,
    bars_to_table,
    content_hash,
    create_object_store,
    table_to_bars,
    table_to_trades,
    trades_to_table,
    validate_key,
)


def _bars(n: int = 5) -> list[Bar]:
    start = datetime(2026, 8, 31, 22, 0, tzinfo=UTC)
    instrument = uuid4()
    return [
        Bar(
            instrument_id=instrument,
            contract_code="ESZ6",
            timeframe="5m",
            origin_time=start + timedelta(minutes=5 * i),
            origin_tz="America/Chicago",
            open=Decimal("6512.25"),
            high=Decimal("6513.00"),
            low=Decimal("6511.75"),
            close=Decimal("6512.50") + Decimal(i) * Decimal("0.25"),
            volume=Decimal(100 + i),
            trade_count=10,
            vwap=Decimal("6512.43750000"),
            data_revision="rev-1",
            provenance="fixture",
        )
        for i in range(n)
    ]


def test_bars_round_trip_through_parquet(tmp_path: Path) -> None:
    store = LocalParquetStore(tmp_path)
    bars = _bars()
    stored = store.put_table("bars/ESZ6/5m.parquet", bars_to_table(bars), {"provenance": "fixture"})

    assert stored.row_count == 5
    assert stored.content_hash == content_hash(bars_to_table(bars))
    assert store.exists("bars/ESZ6/5m.parquet")
    assert store.list_keys() == ["bars/ESZ6/5m.parquet"]
    assert store.get_metadata("bars/ESZ6/5m.parquet") == {
        "provenance": "fixture",
        "content_hash": stored.content_hash,
    }
    assert table_to_bars(store.get_table("bars/ESZ6/5m.parquet")) == bars


def test_trades_round_trip_preserves_decimals(tmp_path: Path) -> None:
    trade = Trade(
        instrument_id=uuid4(),
        sequence=0,
        trade_time=datetime(2026, 8, 31, 0, 0, 8, 870285, tzinfo=UTC),
        trade_tz="UTC",
        price=Decimal("112853.88"),
        size=Decimal("0.50142501"),
        side="sell",
        venue="COINBASE",
        data_revision="rev-1",
        provenance="fixture",
    )
    store = LocalParquetStore(tmp_path)
    store.put_table("trades/BTC-USD.parquet", trades_to_table([trade]))
    [back] = table_to_trades(store.get_table("trades/BTC-USD.parquet"))
    assert back == trade
    assert back.size == Decimal("0.50142501")


def test_content_hash_is_independent_of_row_encoding_details() -> None:
    table = bars_to_table(_bars())
    assert content_hash(table) == content_hash(bars_to_table(table_to_bars(table)))
    assert content_hash(table) != content_hash(bars_to_table(_bars(4)))


@pytest.mark.parametrize("key", ["", "/abs.parquet", "../escape.parquet", "a//b.parquet", "a/./b"])
def test_invalid_keys_are_rejected(key: str) -> None:
    with pytest.raises(StorageKeyError):
        validate_key(key)


def test_missing_objects_raise(tmp_path: Path) -> None:
    store = LocalParquetStore(tmp_path)
    with pytest.raises(ObjectNotFoundError):
        store.get_table("nope.parquet")
    with pytest.raises(ObjectNotFoundError):
        store.delete("nope.parquet")


def test_local_store_satisfies_protocol_and_factory(tmp_path: Path) -> None:
    store = create_object_store("local", local_root=tmp_path)
    assert isinstance(store, ObjectStore)
    assert store.backend == "local"


def test_supabase_backend_is_an_explicit_stub() -> None:
    with pytest.raises(ValueError, match="requires"):
        SupabaseStorageStore("", "", "")
    stub = SupabaseStorageStore("http://127.0.0.1:54321", "market-snapshots", "service-role")
    assert isinstance(stub, ObjectStore)
    with pytest.raises(NotImplementedError, match="Stage 3"):
        stub.exists("anything.parquet")
