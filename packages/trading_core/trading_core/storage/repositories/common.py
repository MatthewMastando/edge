"""Row decoding shared by repositories. JSONB comes back as ``dict`` or text."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from uuid import UUID

from trading_core.domain.jobs import RunStage, Usage

if TYPE_CHECKING:
    from pydantic import JsonValue


def as_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    msg = f"expected uuid, got {type(value).__name__}"
    raise TypeError(msg)


def as_uuid_or_none(value: object) -> UUID | None:
    if value is None:
        return None
    return as_uuid(value)


def as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    msg = f"expected datetime, got {type(value).__name__}"
    raise TypeError(msg)


def as_datetime_or_none(value: object) -> datetime | None:
    if value is None:
        return None
    return as_datetime(value)


def as_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        msg = "expected int, got bool"
        raise TypeError(msg)
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int(value)
    msg = f"expected int, got {type(value).__name__}"
    raise TypeError(msg)


def as_str(value: object, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    if isinstance(value, str):
        return value
    msg = f"expected str, got {type(value).__name__}"
    raise TypeError(msg)


def as_str_or_none(value: object) -> str | None:
    if value is None:
        return None
    return as_str(value)


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    msg = f"expected bool, got {type(value).__name__}"
    raise TypeError(msg)


def as_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    msg = f"expected decimal, got {type(value).__name__}"
    raise TypeError(msg)


def as_decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return as_decimal(value)


def json_param(value: object) -> str:
    """Bind JSONB as text and ``cast(... as jsonb)`` in SQL (avoids ``::`` bind parsing)."""
    return json.dumps(value, default=_json_default)


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    msg = f"cannot encode {type(value).__name__} as JSON"
    raise TypeError(msg)


def as_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, list):
        return [as_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): as_json_value(item) for key, item in value.items()}
    return str(value)


def as_json_dict(value: object) -> dict[str, JsonValue]:
    parsed: object = json.loads(value) if isinstance(value, str) else value
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        msg = "expected a JSON object"
        raise TypeError(msg)
    return {str(key): as_json_value(item) for key, item in parsed.items()}


def as_usage(value: object) -> Usage:
    data = as_json_dict(value)
    if not data:
        return Usage()
    return Usage.model_validate(data)


_STAGES = frozenset(
    {
        "resolve_instrument",
        "capture_snapshot",
        "deterministic_ta",
        "gather_context",
        "synthesize",
        "critique",
        "validate",
        "repair",
        "persist",
        "notify",
    }
)


def as_stages(value: object) -> list[RunStage]:
    if not isinstance(value, list):
        return []
    stages: list[RunStage] = []
    for item in value:
        if isinstance(item, str) and item in _STAGES:
            stages.append(cast("RunStage", item))
    return stages


def uuid_array(ids: list[UUID]) -> str:
    """Comma-separated ids for ``string_to_array`` so the bind stays text."""
    return ",".join(str(item) for item in ids)


def text_array(values: list[str]) -> str:
    """Unit-separator list for ``string_to_array``. Tags are short and server-built."""
    return "\x1f".join(values)


def like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
