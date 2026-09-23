"""LLM provider interface (spec section 6). One orchestrated workflow calls ``respond`` inside a
bounded tool loop; the provider never executes tools itself.

No tool exposed through this interface may submit, modify or cancel broker orders, run shell
commands, execute arbitrary code or perform unrestricted HTTP requests.
"""

from __future__ import annotations

import re
from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, JsonValue, field_validator

from trading_core.domain.common import DomainModel
from trading_core.domain.jobs import Usage

MessageRole = Literal["system", "developer", "user", "assistant", "tool"]

# Same expression as the tool_calls CHECK constraint. `order_block` is a detector, not an order.
FORBIDDEN_TOOL_NAME_PATTERN = (
    r"(place|submit|send|create|modify|amend|replace|cancel)_?orders?"
    r"|orders?_(submit|submission|entry|execution|placement|cancel)"
    r"|(^|_)(shell|exec|execute|eval)($|_)"
    r"|http_request"
    r"|paper_?trad"
)
_FORBIDDEN_TOOL_NAME = re.compile(FORBIDDEN_TOOL_NAME_PATTERN, re.IGNORECASE)


def is_forbidden_tool_name(name: str) -> bool:
    """True for broker order writes, shell/exec and unrestricted HTTP.

    Substring checks are intentionally not used: ``order_block`` and ``get_order_blocks`` are
    required TA tools and must stay allowed.
    """
    return _FORBIDDEN_TOOL_NAME.search(name) is not None


class ToolSpec(DomainModel):
    """A typed function tool. ``parameters`` is a JSON Schema object; the server enforces limits."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    description: str = Field(min_length=1, max_length=1000)
    parameters: dict[str, JsonValue]
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    max_calls_per_run: int = Field(default=12, ge=0)
    counts_as_external_retrieval: bool = Field(
        default=False, description="True for web/search/source fetches subject to the 12-call cap."
    )

    @field_validator("name")
    @classmethod
    def _reject_broker_and_shell_tools(cls, name: str) -> str:
        if is_forbidden_tool_name(name):
            msg = f"tool name is not allowed: {name}"
            raise ValueError(msg)
        return name


class ToolCall(DomainModel):
    id: str
    name: str
    arguments: dict[str, JsonValue]


class ToolResult(DomainModel):
    call_id: str
    name: str
    output: JsonValue
    is_error: bool = False


class Message(DomainModel):
    role: MessageRole
    content: str
    tool_call_id: str | None = None


class ModelRequest(DomainModel):
    instructions: str = Field(description="Core model instruction (see spec section 6).")
    messages: list[Message]
    tools: list[ToolSpec] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    response_schema: dict[str, JsonValue] | None = Field(
        default=None, description="JSON Schema the model must satisfy (e.g. the Thesis contract)."
    )
    model: str | None = Field(default=None, description="Server-configured model name.")
    max_output_tokens: int = Field(default=4096, ge=1)
    recording_id: str | None = Field(
        default=None, description="For RecordedProvider: replay this specific recording."
    )


class ModelResponse(DomainModel):
    response_id: str
    provider: str
    model: str | None
    provenance: Literal["recorded", "live"]
    is_demonstration: bool = Field(
        description="True for recorded replays; the UI labels the result as demonstration output."
    )
    output_text: str | None = None
    output_json: dict[str, JsonValue] | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "length", "content_filter", "error"]
    usage: Usage


@runtime_checkable
class Provider(Protocol):
    @property
    def name(self) -> str: ...

    async def respond(self, request: ModelRequest) -> ModelResponse: ...
