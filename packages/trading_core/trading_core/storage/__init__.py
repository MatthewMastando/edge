"""Object storage for Parquet snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from trading_core.storage.base import (
    ObjectNotFoundError,
    ObjectStore,
    StorageKeyError,
    StoredObject,
    validate_key,
)
from trading_core.storage.local import LocalParquetStore
from trading_core.storage.schemas import (
    BARS_SCHEMA,
    TRADES_SCHEMA,
    bars_to_table,
    content_hash,
    table_to_bars,
    table_to_trades,
    trades_to_table,
)
from trading_core.storage.supabase import SupabaseStorageStore

StorageBackend = Literal["local", "supabase"]


def create_object_store(
    backend: StorageBackend,
    *,
    local_root: Path | None = None,
    supabase_url: str = "",
    supabase_bucket: str = "",
    supabase_service_role_key: str = "",
) -> ObjectStore:
    if backend == "local":
        return LocalParquetStore(local_root or Path(".data/parquet"))
    return SupabaseStorageStore(supabase_url, supabase_bucket, supabase_service_role_key)


__all__ = [
    "BARS_SCHEMA",
    "TRADES_SCHEMA",
    "LocalParquetStore",
    "ObjectNotFoundError",
    "ObjectStore",
    "StorageBackend",
    "StorageKeyError",
    "StoredObject",
    "SupabaseStorageStore",
    "bars_to_table",
    "content_hash",
    "create_object_store",
    "table_to_bars",
    "table_to_trades",
    "trades_to_table",
    "validate_key",
]
