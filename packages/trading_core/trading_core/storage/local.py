"""Local-filesystem Parquet backend used in dev, fixture mode and CI."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow.parquet as pq

from trading_core.storage.base import (
    METADATA_PREFIX,
    ObjectNotFoundError,
    StoredObject,
    validate_key,
)
from trading_core.storage.schemas import content_hash

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import pyarrow as pa


class LocalParquetStore:
    backend = "local"

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, key: str) -> Path:
        path = (self._root / validate_key(key)).resolve()
        if self._root not in path.parents:
            msg = f"key escapes store root: {key!r}"
            raise ValueError(msg)
        return path

    def put_table(
        self, key: str, table: pa.Table, metadata: Mapping[str, str] | None = None
    ) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = content_hash(table)
        merged = {f"{METADATA_PREFIX}{k}": v for k, v in (metadata or {}).items()}
        merged[f"{METADATA_PREFIX}content_hash"] = digest
        existing = table.schema.metadata or {}
        schema_metadata = {**existing, **{k.encode(): v.encode() for k, v in merged.items()}}
        stamped = table.replace_schema_metadata(schema_metadata)
        tmp = path.with_suffix(path.suffix + ".tmp")
        pq.write_table(stamped, tmp, compression="zstd")
        tmp.replace(path)
        return StoredObject(
            backend=self.backend,
            key=key,
            size_bytes=path.stat().st_size,
            row_count=table.num_rows,
            content_hash=digest,
            metadata=dict(metadata or {}),
        )

    def get_table(self, key: str) -> pa.Table:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        return pq.read_table(path)

    def get_metadata(self, key: str) -> dict[str, str]:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        raw = pq.read_schema(path).metadata or {}
        return {
            k.decode()[len(METADATA_PREFIX) :]: v.decode()
            for k, v in raw.items()
            if k.decode().startswith(METADATA_PREFIX)
        }

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list_keys(self, prefix: str = "") -> list[str]:
        base = self._root if not prefix else self._path(prefix.rstrip("/"))
        if not base.exists():
            return []
        return sorted(
            p.relative_to(self._root).as_posix() for p in base.rglob("*.parquet") if p.is_file()
        )

    def delete(self, key: str) -> None:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        path.unlink()
