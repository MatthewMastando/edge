"""Publish every shared contract in the OpenAPI document, even before a route returns it.

FastAPI only emits component schemas for models referenced by routes. Workers A/B/C need the full
set (TAFeature, Thesis, Job, Run ...) in the generated TypeScript from day one, so we merge the
Pydantic JSON schemas of ``CONTRACT_MODELS`` into ``components.schemas``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from trading_core.domain import CONTRACT_MODELS
from trading_core.harness.provider import (
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResult,
    ToolSpec,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

EXTRA_CONTRACT_MODELS = (ModelRequest, ModelResponse, ToolSpec, ToolCall, ToolResult)

REF_TEMPLATE = "#/components/schemas/{model}"


def contract_schemas() -> dict[str, Any]:
    models: list[type[BaseModel]] = [*CONTRACT_MODELS, *EXTRA_CONTRACT_MODELS]
    _, top = models_json_schema(
        [(model, "validation") for model in models], ref_template=REF_TEMPLATE
    )
    defs: dict[str, Any] = top.get("$defs", {})
    return dict(sorted(defs.items()))


def build_openapi(app: FastAPI) -> dict[str, Any]:
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        separate_input_output_schemas=False,
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for name, definition in contract_schemas().items():
        components.setdefault(name, definition)
    schema["components"]["schemas"] = dict(sorted(components.items()))
    return schema


def openapi_json(app: FastAPI) -> str:
    """Deterministic serialization used by the contracts-current CI check."""
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
