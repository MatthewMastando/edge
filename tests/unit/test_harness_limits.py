"""Tool permissions, argument limits, validation repair and secret redaction."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from trading_core.domain.common import CalcVersion
from trading_core.harness.provider import ToolSpec
from trading_core.harness.secrets import redact
from trading_core.harness.thesis_builder import assemble_thesis
from trading_core.harness.tools import (
    ArgumentLimitError,
    build_research_registry,
    enforce_arguments,
    redact_json,
)
from trading_core.harness.validation import repair_thesis, validate_thesis
from trading_core.harness.workflow import _lookup
from trading_core.ta import CALC_VERSION, DetectorRegistry
from trading_core.ta.detectors.fvg import FvgDetector


class _LaterFvg(FvgDetector):
    @property
    def calc_version(self) -> CalcVersion:
        return "9.9.9"


def test_detector_lookup_stays_on_calc_1_0_0() -> None:
    registry = DetectorRegistry()
    registry.register(_LaterFvg())
    assert _lookup(registry, "fvg") is None
    current = FvgDetector()
    registry.register(current)
    found = _lookup(registry, "fvg")
    assert found is current
    assert found is not None
    assert found.calc_version == CALC_VERSION


def test_registry_keeps_order_block_and_rejects_order_writes() -> None:
    registry = build_research_registry()
    assert "order_block" in registry.names()
    assert "search_sources" in registry.names()
    search = next(spec for spec in registry.specs() if spec.name == "search_sources")
    assert search.counts_as_external_retrieval is True
    for name in ("submit_order", "run_shell", "http_request", "cancel_order"):
        with pytest.raises(ValidationError):
            ToolSpec(
                name=name,
                description="Must not be registered.",
                parameters={"type": "object", "properties": {}},
                version="1.0.0",
            )


def test_argument_limits_are_enforced() -> None:
    registry = build_research_registry()
    bars = next(spec for spec in registry.specs() if spec.name == "get_bars")
    enforce_arguments(bars, {"symbol": "6EZ6", "limit": 20})
    with pytest.raises(ArgumentLimitError):
        enforce_arguments(bars, {"symbol": "6EZ6", "limit": 21})
    with pytest.raises(ArgumentLimitError):
        enforce_arguments(bars, {"symbol": "6EZ6", "extra": "no"})
    with pytest.raises(ArgumentLimitError):
        enforce_arguments(bars, {"symbol": "x" * 4000})
    with pytest.raises(ArgumentLimitError, match="symbol"):
        enforce_arguments(bars, {})
    with pytest.raises(ArgumentLimitError, match="symbol"):
        enforce_arguments(bars, {"limit": 5})


def test_one_repair_drops_unmatched_prices_and_unknown_evidence() -> None:
    feature_id = uuid4()
    unknown = uuid4()
    thesis = assemble_thesis(
        run_id=uuid4(),
        instrument_id=uuid4(),
        symbol="6EZ6",
        asset_class="futures",
        contract_code="6EZ6",
        venue="CME",
        horizon="2-5 sessions",
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        feature_rows=[{"id": str(feature_id), "detector": "order_block", "direction": "bullish"}],
        model_json={
            "stance": "bullish",
            "plan": {"entry": "1.10", "invalidation": "1.00", "target": "1.20"},
            "technical_findings": [
                {"feature_id": str(unknown), "summary": "Invented level."},
            ],
            "supporting_evidence": [
                {
                    "stance": "supporting",
                    "claim": "A source that was never stored.",
                    "source_id": str(uuid4()),
                    "retrieved_at": "2026-09-01T00:00:00Z",
                }
            ],
        },
        model_text=None,
        provider="recorded",
        model=None,
        provenance="recorded",
        is_demonstration=True,
        stub_detectors=["fvg"],
        warnings=[],
        secrets=(),
    )
    levels = {feature_id: {Decimal("1.10")}}
    known = {feature_id}
    first = validate_thesis(
        thesis,
        known_feature_ids=known,
        feature_levels=levels,
        known_source_ids=set(),
        known_excerpt_ids=set(),
        tick_value=Decimal("6.25"),
        point_value=Decimal("125000"),
    )
    assert first.passed is False
    repaired = repair_thesis(
        thesis,
        known_feature_ids=known,
        feature_levels=levels,
        known_source_ids=set(),
        known_excerpt_ids=set(),
        tick_value=Decimal("6.25"),
        point_value=Decimal("125000"),
    )
    second = validate_thesis(
        repaired,
        known_feature_ids=known,
        feature_levels=levels,
        known_source_ids=set(),
        known_excerpt_ids=set(),
        tick_value=Decimal("6.25"),
        point_value=Decimal("125000"),
        repair_attempted=True,
    )
    assert second.passed is True
    assert second.repair_attempted is True
    assert repaired.plan.entry == Decimal("1.10")
    assert repaired.plan.invalidation is None
    assert repaired.plan.target is None
    assert [item.feature_id for item in repaired.technical_findings] == [feature_id]
    assert repaired.supporting_evidence == []
    assert repaired.is_demonstration is True


def test_tool_arguments_redact_secrets() -> None:
    secret = "super-secret-token"
    redacted = redact_json({"query": f"look up {secret}", "nested": {"note": secret}}, (secret,))
    assert secret not in str(redacted)
    assert isinstance(redacted, dict)
    assert redacted["query"] == "look up [redacted]"


def test_secrets_are_redacted() -> None:
    secret = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
    text = f"Bearer abcdefghijklmnop and sk-abcdefghijklmnop and {secret}"
    redacted = redact(text, (secret,))
    assert "Bearer [redacted]" in redacted
    assert "sk-" not in redacted
    assert secret not in redacted
    assert "127.0.0.1" not in redacted
