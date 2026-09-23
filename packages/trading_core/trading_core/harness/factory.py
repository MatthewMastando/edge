"""Construct the model provider the worker and API share."""

from __future__ import annotations

from typing import TYPE_CHECKING

from trading_core.harness.openai_stub import OpenAIResponsesProvider
from trading_core.harness.recorded import RecordedProvider

if TYPE_CHECKING:
    from pathlib import Path

    from trading_core.harness.provider import Provider


def load_model_provider(*, provider: str, recordings_root: Path, model: str | None) -> Provider:
    """Recorded replays are the default. The OpenAI class is a Stage 3 stub."""
    if provider == "openai":
        return OpenAIResponsesProvider(model=model or None)
    if not recordings_root.is_dir():
        return RecordedProvider([])
    return RecordedProvider.from_directory(recordings_root)
