"""Supabase Storage backend. Stub in Stage 0: configuration surface only.

Stage 3 implements uploads via the Storage REST API (service role, server side only). Until then
every method raises so a misconfigured deployment fails loudly instead of silently writing nowhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pyarrow as pa

    from trading_core.storage.base import StoredObject


class SupabaseStorageStore:
    backend = "supabase"

    def __init__(self, url: str, bucket: str, service_role_key: str) -> None:
        if not url or not bucket or not service_role_key:
            msg = (
                "SupabaseStorageStore requires SUPABASE_URL, SUPABASE_STORAGE_BUCKET "
                "and SUPABASE_SERVICE_ROLE_KEY"
            )
            raise ValueError(msg)
        self._url = url.rstrip("/")
        self._bucket = bucket
        self._service_role_key = service_role_key

    @property
    def bucket(self) -> str:
        return self._bucket

    def _not_implemented(self) -> NotImplementedError:
        return NotImplementedError(
            "SupabaseStorageStore is a Stage 3 deliverable; set TRW_STORAGE_BACKEND=local"
        )

    def put_table(
        self, key: str, table: pa.Table, metadata: Mapping[str, str] | None = None
    ) -> StoredObject:
        raise self._not_implemented()

    def get_table(self, key: str) -> pa.Table:
        raise self._not_implemented()

    def get_metadata(self, key: str) -> dict[str, str]:
        raise self._not_implemented()

    def exists(self, key: str) -> bool:
        raise self._not_implemented()

    def list_keys(self, prefix: str = "") -> list[str]:
        raise self._not_implemented()

    def delete(self, key: str) -> None:
        raise self._not_implemented()
