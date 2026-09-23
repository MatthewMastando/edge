"""LLM provider interface (spec section 6). One orchestrated workflow calls ``respond`` inside a
bounded tool loop; the provider never executes tools itself.

No tool exposed through this interface may submit, modify or cancel broker orders, run shell
commands, execute arbitrary code or perform unrestricted HTTP requests.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, JsonValue

from trading_core.domain.common import DomainModel
from trading_core.domain.jobs import Usage

MessageRole = Literal["system", "developer", "user", "assistant", "tool"]

FORBIDDEN_TOOL_NAME_FRAGMENTS: frozenset[str] = frozenset(
    {"order", "execute", "submit", "cancel_order", "modify_order", "shell", "exec", "http_request"}
)
"""Tool registries must reject any tool whose name contains one of these fragments."""


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
