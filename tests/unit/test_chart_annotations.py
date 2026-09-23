"""Chart annotations are copies of saved feature levels. Invented prices fail validation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from trading_core.domain.ta import Level, TAFeature
from trading_core.harness.annotations import (
    annotation_from_feature,
    annotation_id_for,
    calculations_from_rows,
    same_levels,
    stamp_feature,
)
from trading_core.harness.thesis_builder import assemble_thesis
from trading_core.harness.validation import validate_thesis

FEATURE_ID = UUID("33333333-3333-4333-8333-333333333333")


def _feature() -> TAFeature:
    origin = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)
    return TAFeature(
        id=FEATURE_ID,
        detector="fvg",
        calc_version="1.0.0",
        instrument_id=UUID("11111111-1111-4111-8111-111111111111"),
        contract_code="6EZ6",
        timeframe="5m",
        session="current_session",
        session_calendar_id="cme_globex_fx",
        session_calendar_version="1.0.0",
        direction="bullish",
        levels=[
            Level(name="zone_lower", price=Decimal("1.10"), role="zone_lower"),
            Level(name="zone_upper", price=Decimal("1.20"), role="zone_upper"),
        ],
        state="confirmed",
        origin_time=origin,
        origin_tz="America/Chicago",
        confirmation_time=origin,
        confirmation_tz="America/Chicago",
        as_of=origin,
        as_of_tz="America/Chicago",
        snapshot_id=UUID("22222222-2222-4222-8222-222222222222"),
        data_revision="fixture-test",
        provenance="fixture",
    )


def _row(feature: TAFeature) -> dict[str, object]:
    payload = feature.model_dump(mode="json")
    return {
        "id": feature.id,
        "detector": feature.detector,
        "calc_version": feature.calc_version,
        "levels": payload["levels"],
        "details": payload["details"],
    }


def test_stamped_annotation_roundtrips_to_the_same_levels() -> None:
    feature = stamp_feature(_feature())
    annotation = annotation_from_feature(feature)
    assert annotation.id == annotation_id_for(feature.id)
    assert same_levels(annotation.levels, feature.levels)
    calculations = calculations_from_rows([_row(feature)])
    saved = calculations[feature.id]
    assert saved.annotation.id == annotation.id
    assert saved.calc_version == "1.0.0"
    assert same_levels(saved.annotation.levels, saved.levels)


def test_tampered_annotation_is_not_a_saved_calculation() -> None:
    feature = stamp_feature(_feature())
    row = _row(feature)
    details = row["details"]
    assert isinstance(details, dict)
    raw = details["chart_annotation"]
    assert isinstance(raw, dict)
    levels = raw["levels"]
    assert isinstance(levels, list)
    first = dict(levels[0])
    first["price"] = "9.99"
    forged = {**raw, "levels": [first, *levels[1:]]}
    tampered = {**row, "details": {**details, "chart_annotation": forged}}
    assert calculations_from_rows([tampered]) == {}


def test_unsupported_plan_price_fails_against_saved_levels() -> None:
    feature = stamp_feature(_feature())
    calculations = calculations_from_rows([_row(feature)])
    thesis = assemble_thesis(
        run_id=UUID("44444444-4444-4444-8444-444444444444"),
        instrument_id=feature.instrument_id,
        symbol="6EZ6",
        asset_class="futures",
        contract_code="6EZ6",
        venue="CME",
        horizon="2-5 sessions",
        as_of=feature.as_of,
        feature_rows=[
            {
                "id": str(feature.id),
                "detector": feature.detector,
                "calc_version": feature.calc_version,
                "direction": feature.direction,
                "levels": [
                    {"name": level.name, "price": format(level.price, "f"), "role": level.role}
                    for level in feature.levels
                ],
            }
        ],
        model_json={
            "stance": "bullish",
            "plan": {"entry": "9.99", "invalidation": "1.10", "target": "1.20"},
        },
        model_text=None,
        provider="recorded",
        model=None,
        provenance="recorded",
        is_demonstration=True,
        stub_detectors=[],
        warnings=[],
        secrets=(),
    )
    finding = thesis.technical_findings[0]
    assert finding.annotation_id == annotation_id_for(feature.id)
    assert "zone_lower 1.10" in finding.summary
    result = validate_thesis(
        thesis,
        known_feature_ids={feature.id},
        feature_levels={feature.id: {level.price for level in feature.levels}},
        known_source_ids=set(),
        known_excerpt_ids=set(),
        tick_value=None,
        point_value=None,
        calculations=calculations,
    )
    failed = {check.name for check in result.checks if not check.passed}
    assert failed == {"numeric_crosscheck"}
    assert result.passed is False
