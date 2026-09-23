"""Typed tool registry. Permissions and argument limits are enforced before a handler runs.

There is no shell, no arbitrary code execution, no unrestricted HTTP tool, and no broker
order submission, modification or cancellation. ``order_block`` remains a legal TA tool.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from pydantic import JsonValue

from trading_core.data.adapter import BarsRequest, TradesRequest, UnknownSymbolError
from trading_core.harness.provider import ToolCall, ToolResult, ToolSpec, is_forbidden_tool_name
from trading_core.harness.secrets import redact
from trading_core.storage.db import fetch_all
from trading_core.storage.repositories.artifacts import get_revision, list_artifacts
from trading_core.storage.repositories.jobs import insert_tool_call
from trading_core.storage.repositories.sources import insert_excerpt, insert_source

if TYPE_CHECKING:
    from trading_core.domain.common import Timeframe
    from trading_core.harness.budget import BudgetService
    from trading_core.harness.deps import WorkflowDeps

Permission = Literal["market_read", "research_read", "history_read", "artifact_read"]
ALLOWED_PERMISSIONS = frozenset({"market_read", "research_read", "history_read", "artifact_read"})
_NAME = r"^[a-z][a-z0-9_]{2,63}$"

ToolHandler = Callable[["ToolSession", dict[str, JsonValue]], Awaitable[JsonValue]]

_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1d"}
DETECTORS = (
    "volume_profile",
    "fvg",
    "liquidity_sweep",
    "bos",
    "order_block",
    "rsi_divergence",
)


class ArgumentLimitError(ValueError):
    pass


@dataclass
class ToolDefinition:
    spec: ToolSpec
    permission: Permission
    handler: ToolHandler


@dataclass
class ToolSession:
    deps: WorkflowDeps
    budget: BudgetService
    run_id: UUID
    job_id: UUID
    symbol: str
    timeframe: str
    feature_summaries: list[dict[str, JsonValue]] = field(default_factory=list)
    stub_detectors: set[str] = field(default_factory=set)
    source_ids: list[UUID] = field(default_factory=list)
    excerpt_ids: list[UUID] = field(default_factory=list)
    retrievals: int = 0
    call_counts: dict[str, int] = field(default_factory=dict)
    tool_sequence: int = 0


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        name = definition.spec.name
        if is_forbidden_tool_name(name):
            msg = f"tool name is not allowed: {name}"
            raise ValueError(msg)
        if definition.permission not in ALLOWED_PERMISSIONS:
            msg = f"tool permission is not allowed: {definition.permission}"
            raise ValueError(msg)
        if name in self._tools:
            msg = f"tool already registered: {name}"
            raise ValueError(msg)
        self._tools[name] = definition

    def specs(self) -> list[ToolSpec]:
        return [item.spec for item in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    async def invoke(self, session: ToolSession, call: ToolCall) -> ToolResult:  # noqa: PLR0911
        if is_forbidden_tool_name(call.name) or not _allowed_name(call.name):
            return ToolResult(
                call_id=call.id,
                name=call.name,
                output={"error": "tool is not available"},
                is_error=True,
            )
        definition = self._tools.get(call.name)
        if definition is None:
            return await self._error(session, call, "1.0.0", False, "unknown tool")
        spec = definition.spec
        used = session.call_counts.get(spec.name, 0)
        if used >= spec.max_calls_per_run:
            return await self._error(session, call, spec.version, False, "call limit reached")
        over_cap = session.retrievals >= session.deps.limits.max_external_retrievals
        if spec.counts_as_external_retrieval and over_cap:
            return await self._error(
                session, call, spec.version, True, "external retrieval cap reached"
            )
        try:
            enforce_arguments(spec, call.arguments)
        except ArgumentLimitError as exc:
            return await self._error(
                session, call, spec.version, spec.counts_as_external_retrieval, str(exc)
            )
        session.call_counts[spec.name] = used + 1
        reservation = None
        if spec.counts_as_external_retrieval:
            reservation = await session.budget.reserve(
                category="search",
                provider="fixture",
                estimate=session.deps.limits.retrieval_reserve_usd,
                unit_type="calls",
            )
        try:
            output = await definition.handler(session, call.arguments)
        except Exception as exc:
            if reservation is not None:
                await session.budget.reconcile(reservation, _zero())
            message = redact_json(str(exc), session.deps.secrets)
            return await self._error(
                session, call, spec.version, spec.counts_as_external_retrieval, str(message)
            )
        else:
            if reservation is not None:
                await session.budget.reconcile(reservation, _zero())
            if spec.counts_as_external_retrieval:
                session.retrievals += 1
        safe = redact_json(output, session.deps.secrets)
        await self._record(
            session, call, spec.version, spec.counts_as_external_retrieval, safe, False
        )
        return ToolResult(call_id=call.id, name=call.name, output=safe, is_error=False)

    async def _error(
        self,
        session: ToolSession,
        call: ToolCall,
        version: str,
        external: bool,
        message: str,
    ) -> ToolResult:
        output: JsonValue = {"error": message}
        await self._record(session, call, version, external, output, True)
        return ToolResult(call_id=call.id, name=call.name, output=output, is_error=True)

    async def _record(
        self,
        session: ToolSession,
        call: ToolCall,
        version: str,
        external: bool,
        output: JsonValue,
        is_error: bool,
    ) -> None:
        sequence = session.tool_sequence
        session.tool_sequence += 1
        safe_arguments = _json_object(redact_json(call.arguments, session.deps.secrets))
        async with session.deps.engine.begin() as conn:
            await insert_tool_call(
                conn,
                run_id=session.run_id,
                sequence=sequence,
                tool_name=call.name,
                tool_version=version,
                arguments=safe_arguments,
                output=output,
                is_error=is_error,
                counts_as_external_retrieval=external,
                duration_ms=0,
            )


def _zero() -> Decimal:
    return Decimal(0)


def enforce_arguments(spec: ToolSpec, arguments: dict[str, JsonValue]) -> None:
    encoded = json.dumps(arguments)
    if len(encoded) > 8192:
        msg = "arguments exceed 8192 bytes"
        raise ArgumentLimitError(msg)
    schema = spec.parameters
    if schema.get("type") != "object":
        msg = "tool schema must be an object"
        raise ArgumentLimitError(msg)
    properties = schema.get("properties")
    rules = properties if isinstance(properties, dict) else {}
    if schema.get("additionalProperties") is False:
        for key in arguments:
            if key not in rules:
                msg = f"unexpected argument {key}"
                raise ArgumentLimitError(msg)
    required = schema.get("required")
    if isinstance(required, list):
        for name in required:
            if isinstance(name, str) and name not in arguments:
                msg = f"missing argument {name}"
                raise ArgumentLimitError(msg)
    for key, value in arguments.items():
        rule = rules.get(key)
        if isinstance(rule, dict):
            _check_rule(key, value, rule)


def _check_rule(key: str, value: JsonValue, rule: dict[str, JsonValue]) -> None:
    expected = rule.get("type")
    if expected == "string":
        if not isinstance(value, str):
            msg = f"{key} must be a string"
            raise ArgumentLimitError(msg)
        max_length = rule.get("maxLength")
        limit = max_length if isinstance(max_length, int) else 2000
        if len(value) > limit:
            msg = f"{key} exceeds {limit} characters"
            raise ArgumentLimitError(msg)
        enum = rule.get("enum")
        if isinstance(enum, list) and value not in enum:
            msg = f"{key} is not an allowed value"
            raise ArgumentLimitError(msg)
    elif expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            msg = f"{key} must be an integer"
            raise ArgumentLimitError(msg)
        minimum = rule.get("minimum")
        maximum = rule.get("maximum")
        if isinstance(minimum, int) and value < minimum:
            msg = f"{key} is below {minimum}"
            raise ArgumentLimitError(msg)
        if isinstance(maximum, int) and value > maximum:
            msg = f"{key} is above {maximum}"
            raise ArgumentLimitError(msg)


def _allowed_name(name: str) -> bool:
    return re.fullmatch(_NAME, name) is not None


def _schema(
    properties: dict[str, object], required: list[str] | None = None
) -> dict[str, JsonValue]:
    return cast(
        "dict[str, JsonValue]",
        {
            "type": "object",
            "additionalProperties": False,
            "required": required or [],
            "properties": properties,
        },
    )


def _spec(
    name: str,
    description: str,
    parameters: dict[str, JsonValue],
    *,
    external: bool = False,
    max_calls: int = 4,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters=parameters,
        version="1.0.0",
        max_calls_per_run=max_calls,
        counts_as_external_retrieval=external,
    )


def build_research_registry(*, include_web: bool = True) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            spec=_spec(
                "resolve_instrument",
                "Resolve a symbol to an instrument and listed contract, if any.",
                _schema({"symbol": {"type": "string", "maxLength": 32}}, ["symbol"]),
            ),
            permission="market_read",
            handler=_resolve,
        )
    )
    registry.register(
        ToolDefinition(
            spec=_spec(
                "get_bars",
                "Return a short slice of completed bars. Entire histories are not returned.",
                _schema(
                    {
                        "symbol": {"type": "string", "maxLength": 32},
                        "timeframe": {"type": "string", "enum": sorted(_TIMEFRAMES)},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    ["symbol"],
                ),
            ),
            permission="market_read",
            handler=_bars,
        )
    )
    registry.register(
        ToolDefinition(
            spec=_spec(
                "get_trades",
                "Return trade-print coverage for a symbol without dumping the full tape.",
                _schema({"symbol": {"type": "string", "maxLength": 32}}, ["symbol"]),
            ),
            permission="market_read",
            handler=_trades,
        )
    )
    registry.register(
        ToolDefinition(
            spec=_spec(
                "get_quotes",
                "Quote coverage. The fixture adapter has no quote feed.",
                _schema({"symbol": {"type": "string", "maxLength": 32}}, ["symbol"]),
            ),
            permission="market_read",
            handler=_quotes,
        )
    )
    for name in DETECTORS:
        registry.register(
            ToolDefinition(
                spec=_spec(
                    name,
                    f"Read saved {name} features. Does not invent levels.",
                    _schema({"symbol": {"type": "string", "maxLength": 32}}),
                    max_calls=2,
                ),
                permission="market_read",
                handler=_detector(name),
            )
        )
    if include_web:
        registry.register(
            ToolDefinition(
                spec=_spec(
                    "search_sources",
                    "Retrieve a labeled fixture source excerpt. Counts against the retrieval cap.",
                    _schema(
                        {
                            "query": {"type": "string", "maxLength": 300},
                            "max_results": {"type": "integer", "minimum": 1, "maximum": 5},
                        },
                        ["query"],
                    ),
                    external=True,
                    max_calls=12,
                ),
                permission="research_read",
                handler=_search,
            )
        )
        registry.register(
            ToolDefinition(
                spec=_spec(
                    "list_catalysts",
                    "List fixture calendar coverage. Live calendars are not configured.",
                    _schema({"symbol": {"type": "string", "maxLength": 32}}, ["symbol"]),
                    external=True,
                    max_calls=4,
                ),
                permission="research_read",
                handler=_catalysts,
            )
        )
    registry.register(
        ToolDefinition(
            spec=_spec(
                "get_user_history",
                "Read imported fills for the owner. Empty until a CSV import exists.",
                _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 20}}),
            ),
            permission="history_read",
            handler=_history,
        )
    )
    registry.register(
        ToolDefinition(
            spec=_spec(
                "get_prior_artifacts",
                "List prior artifacts for the current owner.",
                _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 20}}),
            ),
            permission="artifact_read",
            handler=_prior_artifacts,
        )
    )
    registry.register(
        ToolDefinition(
            spec=_spec(
                "get_artifact_revision",
                "Read one immutable artifact revision.",
                _schema({"revision_id": {"type": "string", "maxLength": 36}}, ["revision_id"]),
            ),
            permission="artifact_read",
            handler=_revision,
        )
    )
    return registry


def _detector(name: str) -> ToolHandler:
    async def handler(session: ToolSession, arguments: dict[str, JsonValue]) -> JsonValue:
        del arguments
        if name in session.stub_detectors:
            return {
                "detector": name,
                "status": "stub",
                "features": [],
                "note": "Detector is not registered. No levels were invented.",
            }
        features = [item for item in session.feature_summaries if item.get("detector") == name]
        return cast("JsonValue", {"detector": name, "status": "saved", "features": features})

    return handler


async def _resolve(session: ToolSession, arguments: dict[str, JsonValue]) -> JsonValue:
    symbol = _required_str(arguments, "symbol")
    try:
        resolved = await session.deps.adapter.resolve(symbol)
    except UnknownSymbolError as exc:
        return {"error": str(exc)}
    contract = resolved.contract.contract_code if resolved.contract else None
    return {
        "symbol": resolved.instrument.symbol,
        "venue": resolved.instrument.venue,
        "asset_class": resolved.instrument.asset_class,
        "contract_code": contract,
        "provenance": resolved.instrument.provenance,
    }


async def _bars(session: ToolSession, arguments: dict[str, JsonValue]) -> JsonValue:
    symbol = _required_str(arguments, "symbol")
    timeframe = arguments.get("timeframe", session.timeframe)
    if not isinstance(timeframe, str) or timeframe not in _TIMEFRAMES:
        timeframe = session.timeframe
    limit = arguments.get("limit", 20)
    if not isinstance(limit, int):
        limit = 20
    series = await session.deps.adapter.get_bars(
        BarsRequest(symbol=symbol, timeframe=cast("Timeframe", timeframe), limit=limit)
    )
    bars: list[dict[str, JsonValue]] = [
        {
            "origin_time": bar.origin_time.isoformat(),
            "open": format(bar.open, "f"),
            "high": format(bar.high, "f"),
            "low": format(bar.low, "f"),
            "close": format(bar.close, "f"),
        }
        for bar in series.bars[-20:]
    ]
    return cast(
        "JsonValue",
        {
            "provenance": series.provenance,
            "data_revision": series.data_revision,
            "count": len(series.bars),
            "bars": bars,
            "note": "Limited slice. The full history is not part of the model context.",
        },
    )


async def _trades(session: ToolSession, arguments: dict[str, JsonValue]) -> JsonValue:
    symbol = _required_str(arguments, "symbol")
    batch = await session.deps.adapter.get_trades(TradesRequest(symbol=symbol, limit=1))
    last = format(batch.trades[-1].price, "f") if batch.trades else None
    return {
        "provenance": batch.provenance,
        "trade_count_returned": len(batch.trades),
        "last_price": last,
        "note": "Trade tape is not copied into the model context.",
    }


async def _quotes(session: ToolSession, arguments: dict[str, JsonValue]) -> JsonValue:
    del session
    return {
        "symbol": arguments.get("symbol"),
        "available": False,
        "reason": "No quote feed is configured. Missing quotes are not zero.",
    }


async def _search(session: ToolSession, arguments: dict[str, JsonValue]) -> JsonValue:
    query = _required_str(arguments, "query")
    now = datetime.now(UTC)
    text = (
        f"Fixture excerpt for {query}. No live page was fetched. "
        "Treat this as demonstration context, not a market fact."
    )
    async with session.deps.engine.begin() as conn:
        source_id = await insert_source(
            conn,
            kind="web_search",
            url=None,
            title=f"Fixture search: {query[:80]}",
            publisher="fixture",
            published_at=None,
            retrieved_at=now,
            provider="fixture",
            provenance="fixture",
        )
        excerpt = await insert_excerpt(
            conn,
            source_id=source_id,
            text=text,
            published_at=None,
            retrieved_at=now,
            provenance="fixture",
            kind="web_search",
        )
    session.source_ids.append(source_id)
    session.excerpt_ids.append(excerpt.id)
    return {
        "provenance": "fixture",
        "is_demonstration": True,
        "results": [
            {
                "source_id": str(source_id),
                "excerpt_id": str(excerpt.id),
                "text": text,
            }
        ],
    }


async def _catalysts(session: ToolSession, arguments: dict[str, JsonValue]) -> JsonValue:
    del session
    return {
        "symbol": arguments.get("symbol"),
        "provenance": "fixture",
        "catalysts": [],
        "note": "Live release calendars are not configured.",
    }


async def _history(session: ToolSession, arguments: dict[str, JsonValue]) -> JsonValue:
    del arguments
    owner = session.deps.owner_id
    if owner is None:
        return {"fills": [], "note": "No owner scope."}
    async with session.deps.engine.begin() as conn:
        rows = await fetch_all(
            conn,
            """
            select symbol_raw, side, quantity, price, fill_time
            from imported_fills f
            join import_batches b on b.id = f.batch_id
            where b.owner_id = :owner_id
            order by fill_time desc
            limit 20
            """,
            {"owner_id": owner},
        )
    return {"fills": [_public_row(row) for row in rows], "provenance": "fixture"}


async def _prior_artifacts(session: ToolSession, arguments: dict[str, JsonValue]) -> JsonValue:
    limit = arguments.get("limit", 10)
    if not isinstance(limit, int):
        limit = 10
    owner = session.deps.owner_id
    if owner is None:
        return {"artifacts": []}
    async with session.deps.engine.begin() as conn:
        rows = await list_artifacts(conn, owner, limit=limit)
    return {
        "artifacts": [
            {"id": str(row["id"]), "title": str(row["title"]), "kind": str(row["kind"])}
            for row in rows
        ]
    }


async def _revision(session: ToolSession, arguments: dict[str, JsonValue]) -> JsonValue:
    raw = _required_str(arguments, "revision_id")
    try:
        revision_id = UUID(raw)
    except ValueError:
        return {"error": "revision_id is not a UUID"}
    async with session.deps.engine.begin() as conn:
        row = await get_revision(conn, revision_id)
    if row is None:
        return {"error": "revision not found"}
    presentation = row["presentation_markdown"]
    text = presentation if isinstance(presentation, str) else ""
    number = row["revision_number"]
    return {
        "id": str(row["id"]),
        "revision_number": number if isinstance(number, int) else 0,
        "is_demonstration": row["is_demonstration"] is True,
        "presentation_markdown": text[:2000],
    }


def _required_str(arguments: dict[str, JsonValue], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str):
        msg = f"{key} must be a string"
        raise ArgumentLimitError(msg)
    return value


def _public_row(row: dict[str, object]) -> dict[str, JsonValue]:
    published: dict[str, JsonValue] = {}
    for key, value in row.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            published[key] = value
        else:
            published[key] = str(value)
    return published


def _json_object(value: JsonValue) -> dict[str, JsonValue]:
    if isinstance(value, dict):
        return value
    return {}


def redact_json(value: JsonValue, secrets: tuple[str, ...]) -> JsonValue:
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, list):
        return [redact_json(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: redact_json(item, secrets) for key, item in value.items()}
    return value
