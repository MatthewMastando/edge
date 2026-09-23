"""Replays saved model responses. Output is always labeled ``recorded`` / demonstration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from trading_core.domain.common import DomainModel
from trading_core.harness.provider import ModelRequest, ModelResponse

if TYPE_CHECKING:
    from pathlib import Path

RECORDED_PROVIDER_NAME = "recorded"


class RecordingMatch(DomainModel):
    """How a recording is selected when the request does not name one explicitly."""

    contains: str | None = Field(
        default=None, description="Substring that must appear in the last user message."
    )
    model: str | None = None


class Recording(DomainModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")
    description: str
    match: RecordingMatch = Field(default_factory=RecordingMatch)
    response: ModelResponse


class NoRecordingError(LookupError):
    pass


class RecordedProvider:
    def __init__(self, recordings: list[Recording]) -> None:
        self._recordings = {r.id: r for r in recordings}
        for recording in recordings:
            if (
                recording.response.provenance != "recorded"
                or not recording.response.is_demonstration
            ):
                msg = f"recording {recording.id!r} must be labeled recorded/demonstration"
                raise ValueError(msg)

    @classmethod
    def from_directory(cls, directory: Path) -> RecordedProvider:
        recordings = [
            Recording.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        ]
        return cls(recordings)

    @property
    def name(self) -> str:
        return RECORDED_PROVIDER_NAME

    @property
    def recording_ids(self) -> list[str]:
        return sorted(self._recordings)

    def select(self, request: ModelRequest) -> Recording:
        if request.recording_id is not None:
            try:
                return self._recordings[request.recording_id]
            except KeyError as exc:
                msg = f"no recording {request.recording_id!r}"
                raise NoRecordingError(msg) from exc
        last_user = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        for recording in self._recordings.values():
            match = recording.match
            if match.model is not None and match.model != request.model:
                continue
            if match.contains is not None and match.contains not in last_user:
                continue
            return recording
        msg = "no recording matches the request; pass recording_id or add a recording"
        raise NoRecordingError(msg)

    async def respond(self, request: ModelRequest) -> ModelResponse:
        recording = self.select(request)
        return recording.response.model_copy(update={"provider": RECORDED_PROVIDER_NAME})
