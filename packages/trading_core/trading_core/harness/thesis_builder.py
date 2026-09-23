"""Build a thesis from workflow facts plus a model JSON object.

Computed feature ids come from the deterministic stage. The model may cite them; it may not
introduce prices that do not match those features. Recorded output is always demonstration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pydantic import JsonValue, ValidationError

from trading_core.domain.thesis import (
    EvidenceItem,
    FeatureReference,
    Thesis,
    ThesisVersions,
    TradePlan,
    ValidationCheck,
    ValidationResult,
)
from trading_core.harness.annotations import annotation_id_for
from trading_core.harness.deps import HARNESS_VERSION, PROMPT_VERSION
from trading_core.harness.secrets import redact

if TYPE_CHECKING:
    from datetime import datetime

    from trading_core.domain.common import AssetClass, Provenance, Stance

_STANCES = {"bullish", "bearish", "neutral", "insufficient_evidence"}


def pending_validation() -> ValidationResult:
    return ValidationResult(
        passed=False,
        checks=[ValidationCheck(name="schema", passed=False, detail="pending")],
        repair_attempted=False,
    )


def feature_summaries(raw_features: list[dict[str, JsonValue]]) -> list[FeatureReference]:
    findings: list[FeatureReference] = []
    seen: set[UUID] = set()
    for item in raw_features:
        feature_id = item.get("id")
        detector = item.get("detector")
        direction = item.get("direction")
        if not isinstance(feature_id, str) or not isinstance(detector, str):
            continue
        parsed = UUID(feature_id)
        if parsed in seen:
            continue
        seen.add(parsed)
        label = detector if not isinstance(direction, str) else f"{detector} {direction}"
        version = item.get("calc_version")
        version_note = f" calc {version}" if isinstance(version, str) else ""
        findings.append(
            FeatureReference(
                feature_id=parsed,
                annotation_id=annotation_id_for(parsed),
                summary=_summary(label, version_note, item.get("levels")),
            )
        )
    return findings


def _summary(label: str, version_note: str, levels: JsonValue) -> str:
    text = f"Computed {label}{version_note} feature."
    figures = _figures(levels)
    if figures:
        extra = " Levels: " + ", ".join(figures) + "."
        if len(text) + len(extra) <= 1000:
            text += extra
    return text


def _figures(levels: JsonValue) -> list[str]:
    if not isinstance(levels, list):
        return []
    figures: list[str] = []
    for level in levels:
        if not isinstance(level, dict):
            continue
        name = level.get("name")
        price = level.get("price")
        if isinstance(name, str) and isinstance(price, str):
            figures.append(f"{name} {price}")
    return figures


def tool_versions(raw_features: list[dict[str, JsonValue]]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for item in raw_features:
        detector = item.get("detector")
        version = item.get("calc_version")
        if isinstance(detector, str) and isinstance(version, str):
            versions[detector] = version
    return versions


def assemble_thesis(
    *,
    run_id: UUID,
    instrument_id: UUID,
    symbol: str,
    asset_class: AssetClass,
    contract_code: str | None,
    venue: str,
    horizon: str,
    as_of: datetime,
    feature_rows: list[dict[str, JsonValue]],
    model_json: dict[str, JsonValue],
    model_text: str | None,
    provider: str,
    model: str | None,
    provenance: Provenance,
    is_demonstration: bool,
    stub_detectors: list[str],
    warnings: list[str],
    secrets: tuple[str, ...],
    validation: ValidationResult | None = None,
    thesis_id: UUID | None = None,
) -> Thesis:
    stance = _stance(model_json.get("stance"))
    plan = _plan(model_json.get("plan"))
    findings = feature_summaries(feature_rows)
    known = {item.feature_id for item in findings}
    for extra in _model_findings(model_json.get("technical_findings")):
        if extra.feature_id not in known:
            findings.append(extra)
            known.add(extra.feature_id)
    supporting, opposing = _model_evidence(model_json)
    missing = _strings(model_json.get("missing_data"))
    if stub_detectors:
        missing.append("stub detectors: " + ", ".join(stub_detectors))
    missing.extend(warnings)
    narrative_source = model_text or _string(model_json.get("market_narrative"))
    narrative = redact(narrative_source or _default_narrative(symbol, stub_detectors), secrets)
    macro = redact(
        _string(model_json.get("macro_context"))
        or "No live macro or fundamental sources were retrieved.",
        secrets,
    )
    uncertainty = redact(
        _string(model_json.get("uncertainty"))
        or (
            "Fixture or recorded path. Missing live sources are listed in missing_data. "
            "No trading edge is claimed."
        ),
        secrets,
    )
    rationale = redact(
        _string(model_json.get("rationale"))
        or "Abstaining where inputs are missing. Tools were not given trading authority.",
        secrets,
    )[:4000]
    result = validation or pending_validation()
    presentation = render_presentation(
        symbol=symbol,
        contract_code=contract_code,
        stance=stance,
        narrative=narrative,
        macro=macro,
        uncertainty=uncertainty,
        rationale=rationale,
        is_demonstration=is_demonstration,
        plan_unset=plan.unset_reason,
        calculation_note=_calculation_note(tool_versions(feature_rows)),
    )
    return Thesis(
        id=thesis_id or uuid4(),
        run_id=run_id,
        instrument_id=instrument_id,
        symbol=symbol,
        asset_class=asset_class,
        contract_code=contract_code,
        venue=venue,
        horizon=horizon,
        as_of=as_of,
        stance=stance,
        plan=plan,
        technical_findings=findings,
        market_narrative=narrative,
        macro_context=macro,
        supporting_evidence=supporting,
        opposing_evidence=opposing,
        missing_data=_unique(missing),
        uncertainty=uncertainty,
        rationale=rationale,
        versions=ThesisVersions(
            model=model,
            provider=provider,
            prompt_version=PROMPT_VERSION,
            harness_version=HARNESS_VERSION,
            tool_versions=tool_versions(feature_rows),
        ),
        validation=result,
        presentation_markdown=presentation,
        provenance=provenance,
        is_demonstration=is_demonstration or provenance != "live",
    )


def render_presentation(
    *,
    symbol: str,
    contract_code: str | None,
    stance: str,
    narrative: str,
    macro: str,
    uncertainty: str,
    rationale: str,
    is_demonstration: bool,
    plan_unset: str | None,
    calculation_note: str = "",
) -> str:
    contract = f" ({contract_code})" if contract_code else ""
    banner = ""
    if is_demonstration:
        banner = (
            "> **Demonstration output.** This thesis replays a recorded model response or "
            "fixture data. It is not live research.\n\n"
        )
    unset = f"\n\nPlan unset: {plan_unset}" if plan_unset else ""
    return (
        f"{banner}# {symbol}{contract}\n\n"
        f"**Stance:** {stance}{calculation_note}\n\n"
        f"{narrative}\n\n"
        f"## Context\n\n{macro}\n\n"
        f"## Uncertainty\n\n{uncertainty}\n\n"
        f"## Rationale\n\n{rationale}{unset}\n"
    )


def _calculation_note(versions: dict[str, str]) -> str:
    if not versions:
        return ""
    parts = [f"{name} {versions[name]}" for name in sorted(versions)]
    return "\n\nCalculations: " + ", ".join(parts) + "."


def _stance(value: JsonValue) -> Stance:
    if isinstance(value, str) and value in _STANCES:
        if value == "bullish":
            return "bullish"
        if value == "bearish":
            return "bearish"
        if value == "neutral":
            return "neutral"
    return "insufficient_evidence"


def _plan(value: JsonValue) -> TradePlan:
    if isinstance(value, dict):
        try:
            plan = TradePlan.model_validate(value)
        except ValidationError:
            plan = TradePlan(unset_reason="Model plan did not match the thesis contract.")
    else:
        plan = TradePlan(unset_reason="Model did not provide a conditional plan.")
    unset = plan.entry is None or plan.invalidation is None or plan.target is None
    if unset and not plan.unset_reason:
        plan = plan.model_copy(update={"unset_reason": "Conditional plan was not supported."})
    return plan


def _model_findings(value: JsonValue) -> list[FeatureReference]:
    if not isinstance(value, list):
        return []
    findings: list[FeatureReference] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            findings.append(FeatureReference.model_validate(item))
        except ValidationError:
            continue
    return findings


def _model_evidence(
    model_json: dict[str, JsonValue],
) -> tuple[list[EvidenceItem], list[EvidenceItem]]:
    return _evidence_list(model_json.get("supporting_evidence"), "supporting"), _evidence_list(
        model_json.get("opposing_evidence"), "opposing"
    )


def _evidence_list(value: JsonValue, stance: str) -> list[EvidenceItem]:
    if not isinstance(value, list):
        return []
    items: list[EvidenceItem] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        payload = dict(raw)
        payload["stance"] = stance
        try:
            items.append(EvidenceItem.model_validate(payload))
        except ValidationError:
            continue
    return items


def _strings(value: JsonValue) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _string(value: JsonValue) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _default_narrative(symbol: str, stub_detectors: list[str]) -> str:
    if stub_detectors:
        return (
            f"Research for {symbol} did not compute the stub detectors "
            f"({', '.join(stub_detectors)}). No numerical edge is claimed."
        )
    return f"Research for {symbol} used only computed features and retrieved excerpts."
