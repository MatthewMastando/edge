"""Live OpenAI provider seam. Calls still pass through the budget hooks; the body is Stage 3."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trading_core.harness.provider import ModelRequest, ModelResponse


class LiveProviderUnavailableError(RuntimeError):
    pass


class OpenAIResponsesProvider:
    def __init__(self, *, model: str | None = None) -> None:
        self._model = model

    @property
    def name(self) -> str:
        return "openai"

    async def respond(self, request: ModelRequest) -> ModelResponse:
        del request
        raise LiveProviderUnavailableError(
            "OpenAIResponsesProvider is not implemented; live model calls are Stage 3"
        )
