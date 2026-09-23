from __future__ import annotations

import pytest

from tests.conftest import FIXTURES_DIR
from trading_core.harness import (
    Message,
    ModelRequest,
    NoRecordingError,
    Provider,
    RecordedProvider,
)

INSTRUCTIONS = "Use tools to establish current facts. You have no trading authority."


def _request(text: str, recording_id: str | None = None) -> ModelRequest:
    return ModelRequest(
        instructions=INSTRUCTIONS,
        messages=[Message(role="user", content=text)],
        recording_id=recording_id,
    )


def test_loads_recordings_from_fixtures_directory() -> None:
    provider = RecordedProvider.from_directory(FIXTURES_DIR / "recorded")
    assert isinstance(provider, Provider)
    assert provider.name == "recorded"
    assert "demo-thesis-6ez6" in provider.recording_ids


async def test_replays_are_labeled_as_demonstration() -> None:
    provider = RecordedProvider.from_directory(FIXTURES_DIR / "recorded")
    response = await provider.respond(_request("Research 6EZ6 for the coming week"))
    assert response.provenance == "recorded"
    assert response.is_demonstration is True
    assert response.provider == "recorded"
    assert response.output_json is not None
    assert response.output_json["stance"] == "insufficient_evidence"


async def test_explicit_recording_id_and_missing_match() -> None:
    provider = RecordedProvider.from_directory(FIXTURES_DIR / "recorded")
    by_id = await provider.respond(_request("anything", recording_id="demo-thesis-6ez6"))
    assert by_id.response_id == "rec_demo_6ez6_0001"

    with pytest.raises(NoRecordingError):
        await provider.respond(_request("no recording covers GCZ6 yet"))
    with pytest.raises(NoRecordingError):
        await provider.respond(_request("x", recording_id="does-not-exist"))
