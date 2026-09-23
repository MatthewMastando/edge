"""Object store interface for Parquet market snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import Field

from trading_core.domain.common import DomainModel

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pyarrow as pa

METADATA_PREFIX = "trw."
"""Schema-metadata keys written by the store are namespaced to avoid clashing with writers."""


class StorageKeyError(ValueError):
    """Raised for keys that could escape the store root or are otherwise malformed."""


class ObjectNotFoundError(FileNotFoundError):
    """Raised when a key does not exist in the store."""


class StoredObject(DomainModel):
    """Result of a write: enough to build a :class:`MarketSnapshot` row."""

    backend: str
    key: str
    size_bytes: int = Field(ge=0)
    row_count: int = Field(ge=0)
    content_hash: str
    metadata: dict[str, str] = Field(default_factory=dict)


def validate_key(key: str) -> str:
    """Keys are relative POSIX paths: no absolute paths, no traversal, no empty segments."""
    if not key or key.startswith("/") or key.endswith("/"):
        msg = f"invalid storage key: {key!r}"
        raise StorageKeyError(msg)
    parts = key.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        msg = f"invalid storage key: {key!r}"
        raise StorageKeyError(msg)
    return key


@runtime_checkable
class ObjectStore(Protocol):
    """Minimal store contract. Backends: local filesystem (dev/fixture/CI), Supabase Storage."""

    @property
    def backend(self) -> str: ...

    def put_table(
        self, key: str, table: pa.Table, metadata: Mapping[str, str] | None = None
    ) -> StoredObject: ...

    def get_table(self, key: str) -> pa.Table: ...

    def get_metadata(self, key: str) -> dict[str, str]: ...

    def exists(self, key: str) -> bool: ...

    def list_keys(self, prefix: str = "") -> list[str]: ...

    def delete(self, key: str) -> None: ...
