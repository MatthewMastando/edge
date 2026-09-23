"""OpenAI Responses provider. Recorded remains the default and is still demonstration output."""

from __future__ import annotations

import json

import pytest

from tests.conftest import FIXTURES_DIR
from tests.unit.recording_transport import RecordingTransport
from trading_core.harness.factory import load_model_provider
from trading_core.harness.openai_stub import LiveProviderUnavailableError, OpenAIResponsesProvider
from trading_core.harness.provider import Message, ModelRequest


def _request(*, model: str | None = None) -> ModelRequest:
    return ModelRequest(
        instructions="Research only.",
        messages=[Message(role="user", content="Summarize 6EZ6.")],
        model=model,
    )


def test_recorded_provider_stays_the_default() -> None:
    provider = load_model_provider(
        provider="recorded",
        recordings_root=FIXTURES_DIR / "recorded",
        model=None,
    )
    assert provider.name == "recorded"
    explicit = load_model_provider(
        provider="openai",
        recordings_root=FIXTURES_DIR / "recorded",
        model="server-model",
        api_key="",
    )
    assert explicit.name == "openai"


async def test_openai_missing_key_or_model_invents_nothing() -> None:
    transport = RecordingTransport()
    missing_key = OpenAIResponsesProvider(api_key="", model="server-model", transport=transport)
    with pytest.raises(LiveProviderUnavailableError, match="OPENAI_API_KEY"):
        await missing_key.respond(_request())
    missing_model = OpenAIResponsesProvider(api_key="sk-test", model="", transport=transport)
    with pytest.raises(LiveProviderUnavailableError, match="OPENAI_MODEL"):
        await missing_model.respond(_request())
    assert transport.calls == []


async def test_openai_parses_a_recorded_responses_payload() -> None:
    transport = RecordingTransport()
    payload = {
        "id": "resp_test",
        "model": "server-model",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": '{"stance": "neutral"}'}],
            }
        ],
        "usage": {"input_tokens": 3, "output_tokens": 4},
    }
    transport.add("/v1/responses", json.dumps(payload).encode())
    provider = OpenAIResponsesProvider(api_key="sk-test", model="server-model", transport=transport)
    response = await provider.respond(_request())
    assert response.provenance == "live"
    assert response.is_demonstration is False
    assert response.model == "server-model"
    assert response.output_json == {"stance": "neutral"}
    assert response.usage.actual_cost_usd is None
    assert response.finish_reason == "stop"
    sent = json.loads(transport.calls[0].body or b"{}")
    assert sent["model"] == "server-model"
    assert transport.calls[0].headers["Authorization"] == "Bearer sk-test"
