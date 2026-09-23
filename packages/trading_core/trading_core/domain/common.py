"""Shared primitives for domain models: base config, exact decimals, UTC timestamps, enums."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
)


class DomainModel(BaseModel):
    """Base for every shared contract: immutable, strict about unknown fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def _decimal_to_str(value: Decimal) -> str:
    return format(value, "f")


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


DecimalStr = Annotated[
    Decimal,
    PlainSerializer(_decimal_to_str, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "format": "decimal",
            "description": "Exact decimal encoded as a string (money, prices, sizes).",
        }
    ),
]
"""Exact decimal for money, prices and sizes. Serialized as a string in JSON, `numeric` in SQL."""

UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
"""Timezone-aware datetime normalized to UTC. Pair with an ``*_tz`` field for the original zone."""

TimezoneName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        description="IANA timezone name of the original timestamp, e.g. America/Chicago.",
        examples=["America/Chicago", "America/New_York", "UTC"],
    ),
]

Provenance = Literal["fixture", "recorded", "live"]
"""Where data or model output came from. Anything not ``live`` must be labeled in the UI."""

AssetClass = Literal[
    "futures",
    "equity",
    "etf",
    "crypto_spot",
    "crypto_futures",
    "event_contract",
]

Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d"]

TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14_400,
    "1d": 86_400,
}

Direction = Literal["bullish", "bearish", "neutral"]

Stance = Literal["bullish", "bearish", "neutral", "insufficient_evidence"]

SessionScope = Literal[
    "current_session",
    "prior_session",
    "overnight",
    "rth",
    "eth",
    "anchored",
    "fixed_range",
    "composite",
]

CalcVersion = Annotated[
    str,
    Field(
        pattern=r"^\d+\.\d+\.\d+$",
        description="Semantic version of the calculation that produced this object.",
        examples=["1.0.0"],
    ),
]

DataRevision = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        description=(
            "Identifier of the exact data snapshot a calculation ran against. "
            "Re-running on the same revision must be idempotent."
        ),
    ),
]


class FixtureLabel(DomainModel):
    """Attached to everything produced by the fixture generator so it can never pass as live."""

    provenance: Literal["fixture"] = "fixture"
    generator: str = Field(description="Generator identifier, e.g. trading_core.fixtures.generator")
    generator_version: CalcVersion
    seed: int = Field(ge=0)
    data_revision: DataRevision
    generated_at: UtcDatetime
    notice: str = Field(
        default=(
            "Synthetic demonstration data generated deterministically from a seed. "
            "Not market data. Not investment research."
        )
    )
