"""Parameter parsing. Decimal inputs must be strings so JSON does not lose precision."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import JsonValue


def resolve_parameters(
    defaults: dict[str, JsonValue], overrides: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    unknown = sorted(set(overrides) - set(defaults))
    if unknown:
        msg = f"unknown parameters: {', '.join(unknown)}"
        raise ValueError(msg)
    merged = dict(defaults)
    merged.update(overrides)
    return merged


def param_int(params: dict[str, JsonValue], key: str) -> int:
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{key} must be an integer"
        raise ValueError(msg)
    return value


def param_bool(params: dict[str, JsonValue], key: str) -> bool:
    value = params[key]
    if not isinstance(value, bool):
        msg = f"{key} must be a boolean"
        raise ValueError(msg)
    return value


def param_decimal(params: dict[str, JsonValue], key: str) -> Decimal:
    value = params[key]
    if not isinstance(value, str):
        msg = f"{key} must be a decimal string"
        raise ValueError(msg)
    try:
        return Decimal(value)
    except Exception as exc:
        msg = f"{key} must be a decimal string"
        raise ValueError(msg) from exc


def param_str_list(params: dict[str, JsonValue], key: str) -> list[str]:
    value = params[key]
    if not isinstance(value, list):
        msg = f"{key} must be a list of strings"
        raise ValueError(msg)
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            msg = f"{key} must be a list of strings"
            raise ValueError(msg)
        out.append(item)
    return out


def param_optional_time(params: dict[str, JsonValue], key: str) -> datetime | None:
    value = params[key]
    if value == "" or value is None:
        return None
    if not isinstance(value, str):
        msg = f"{key} must be an ISO-8601 string"
        raise ValueError(msg)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        msg = f"{key} must be an ISO-8601 string"
        raise ValueError(msg) from exc
    if parsed.tzinfo is None:
        msg = f"{key} must include a timezone"
        raise ValueError(msg)
    return parsed.astimezone(UTC)


def param_roll_times(params: dict[str, JsonValue]) -> list[datetime]:
    out: list[datetime] = []
    for raw in param_str_list(params, "roll_times"):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            msg = "roll_times entries must be ISO-8601 timestamps"
            raise ValueError(msg) from exc
        if parsed.tzinfo is None:
            msg = "roll_times entries must include a timezone"
            raise ValueError(msg)
        out.append(parsed.astimezone(UTC))
    return out


def as_object_list(value: JsonValue, key: str) -> list[dict[str, JsonValue]]:
    if not isinstance(value, list):
        msg = f"{key} must be a list of objects"
        raise ValueError(msg)
    out: list[dict[str, JsonValue]] = []
    for item in value:
        if not isinstance(item, dict):
            msg = f"{key} must be a list of objects"
            raise ValueError(msg)
        out.append(item)
    return out
