"""OpenAI Responses API provider. Recorded replays stay the default when this is not selected.

The model name comes from the server setting or the request. No model is hard-coded as verified.
A missing key or model name raises; this provider does not invent a completion.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, cast
from uuid import uuid4

from trading_core.domain.jobs import Usage
from trading_core.harness.provider import (
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResult,
)
from trading_core.harness.secrets import redact
from trading_core.http_client import HttpRequest, HttpxTransport, Transport

if TYPE_CHECKING:
    from pydantic import JsonValue

_URL = "https://api.openai.com/v1/responses"


class LiveProviderUnavailableError(RuntimeError):
    pass


class OpenAIResponsesProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._model = (model or "").strip()
        self._transport = transport or HttpxTransport()

    @property
    def name(self) -> str:
        return "openai"

    async def respond(self, request: ModelRequest) -> ModelResponse:
        if not self._api_key:
            raise LiveProviderUnavailableError(
                "OPENAI_API_KEY is not set. No model output was invented."
            )
        model = (request.model or self._model or "").strip()
        if not model:
            raise LiveProviderUnavailableError(
                "OPENAI_MODEL is not set. No default model is assumed."
            )
        body = _request_body(request, model)
        result = await self._transport.send(
            HttpRequest(
                method="POST",
                url=_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                body=json.dumps(body).encode(),
                timeout_seconds=60,
            )
        )
        raw = result.body.decode("utf-8", errors="replace")
        if result.status >= 400:
            raise LiveProviderUnavailableError(
                redact(f"OpenAI responses HTTP {result.status}: {raw[:300]}", (self._api_key,))
            )
        try:
            parsed: object = json.loads(result.body)
        except json.JSONDecodeError as exc:
            raise LiveProviderUnavailableError("OpenAI response was not JSON") from exc
        if not isinstance(parsed, dict):
            raise LiveProviderUnavailableError("OpenAI response was not an object")
        return _response(cast("dict[str, object]", parsed), model)


def _request_body(request: ModelRequest, model: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": model,
        "instructions": request.instructions,
        "input": _input(request),
        "max_output_tokens": request.max_output_tokens,
    }
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in request.tools
        ]
    if request.response_schema is not None:
        payload["text"] = {
            "format": {
                "type": "json_schema",
                "name": "research_output",
                "schema": request.response_schema,
                "strict": False,
            }
        }
    return payload


def _input(request: ModelRequest) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for message in request.messages:
        if message.role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id or "",
                    "output": message.content,
                }
            )
            continue
        items.append({"role": message.role, "content": message.content})
    for result in request.tool_results:
        items.append(_tool_output(result))
    return items


def _tool_output(result: ToolResult) -> dict[str, object]:
    output = result.output if isinstance(result.output, str) else json.dumps(result.output)
    return {"type": "function_call_output", "call_id": result.call_id, "output": output}


def _response(payload: dict[str, object], model: str) -> ModelResponse:
    output = payload.get("output")
    calls: list[ToolCall] = []
    texts: list[str] = []
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call":
                calls.append(_call(item))
            if item.get("type") == "message":
                texts.extend(_message_text(item))
    text = "\n".join(part for part in texts if part) or None
    output_json = _json_object(text)
    usage = payload.get("usage")
    input_tokens = 0
    output_tokens = 0
    if isinstance(usage, dict):
        input_tokens = _int(usage.get("input_tokens"))
        output_tokens = _int(usage.get("output_tokens"))
    status = str(payload.get("status") or "")
    finish: Literal["stop", "tool_calls", "length", "error"] = "stop"
    if calls:
        finish = "tool_calls"
    if status == "incomplete":
        finish = "length"
    elif status == "failed":
        finish = "error"
    response_id = payload.get("id")
    return ModelResponse(
        response_id=response_id if isinstance(response_id, str) and response_id else uuid4().hex,
        provider="openai",
        model=str(payload.get("model") or model),
        provenance="live",
        is_demonstration=False,
        output_text=text,
        output_json=output_json,
        tool_calls=calls,
        finish_reason=finish,
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            actual_cost_usd=None,
        ),
    )


def _call(item: dict[str, object]) -> ToolCall:
    raw_args = item.get("arguments")
    parsed: object = {}
    if isinstance(raw_args, str) and raw_args:
        parsed = json.loads(raw_args)
    elif isinstance(raw_args, dict):
        parsed = raw_args
    call_id = item.get("call_id") or item.get("id") or uuid4().hex
    name = item.get("name")
    if not isinstance(name, str) or not name:
        raise LiveProviderUnavailableError("OpenAI function call had no name")
    return ToolCall.model_validate(
        {"id": str(call_id), "name": name, "arguments": parsed if isinstance(parsed, dict) else {}}
    )


def _message_text(item: dict[str, object]) -> list[str]:
    content = item.get("content")
    if not isinstance(content, list):
        return []
    texts: list[str] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "output_text":
            text = part.get("text")
            if isinstance(text, str):
                texts.append(text)
    return texts


def _json_object(text: str | None) -> dict[str, JsonValue] | None:
    if text is None:
        return None
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed: object = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return cast("dict[str, JsonValue]", parsed)
    return None


def _int(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0
