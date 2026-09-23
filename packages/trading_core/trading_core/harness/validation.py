"""Schema, numeric and evidence checks for a thesis. One structural repair is allowed."""

from __future__ import annotations

from typing import TYPE_CHECKING

from trading_core.domain.thesis import (
    EvidenceItem,
    Thesis,
    TradePlan,
    ValidationCheck,
    ValidationResult,
)
from trading_core.harness.annotations import (
    SavedCalculation,
    annotation_id_for,
    same_levels,
)

if TYPE_CHECKING:
    from decimal import Decimal
    from uuid import UUID


def validate_thesis(
    thesis: Thesis,
    *,
    known_feature_ids: set[UUID],
    feature_levels: dict[UUID, set[Decimal]],
    known_source_ids: set[UUID],
    known_excerpt_ids: set[UUID],
    tick_value: Decimal | None,
    point_value: Decimal | None,
    repair_attempted: bool = False,
    calculations: dict[UUID, SavedCalculation] | None = None,
) -> ValidationResult:
    checks = [
        _schema_check(thesis),
        _feature_check(thesis, known_feature_ids),
        _numeric_check(thesis, feature_levels),
        _annotation_check(thesis, calculations),
        _evidence_check(thesis, known_source_ids, known_excerpt_ids),
        _risk_check(thesis, tick_value, point_value),
    ]
    return ValidationResult(
        passed=all(check.passed for check in checks),
        checks=checks,
        repair_attempted=repair_attempted,
    )


def repair_thesis(
    thesis: Thesis,
    *,
    known_feature_ids: set[UUID],
    feature_levels: dict[UUID, set[Decimal]],
    known_source_ids: set[UUID],
    known_excerpt_ids: set[UUID],
    tick_value: Decimal | None,
    point_value: Decimal | None,
) -> Thesis:
    """Drop claims that do not resolve to saved features or evidence. Does not invent numbers."""
    findings = [
        item.model_copy(update={"annotation_id": annotation_id_for(item.feature_id)})
        for item in thesis.technical_findings
        if item.feature_id in known_feature_ids
    ]
    known_prices: set[Decimal] = set()
    for finding in findings:
        known_prices.update(feature_levels.get(finding.feature_id, set()))
    plan = _repair_plan(thesis.plan, known_prices)
    supporting = _repair_evidence(thesis.supporting_evidence, known_source_ids, known_excerpt_ids)
    opposing = _repair_evidence(thesis.opposing_evidence, known_source_ids, known_excerpt_ids)
    risk = thesis.risk
    if risk is not None and (
        (risk.tick_value is not None and tick_value is not None and risk.tick_value != tick_value)
        or (
            risk.point_value is not None
            and point_value is not None
            and risk.point_value != point_value
        )
    ):
        risk = risk.model_copy(update={"tick_value": tick_value, "point_value": point_value})
    missing = list(thesis.missing_data)
    if "unsupported numerical claims removed during repair" not in missing:
        missing.append("unsupported numerical claims removed during repair")
    return thesis.model_copy(
        update={
            "technical_findings": findings,
            "plan": plan,
            "supporting_evidence": supporting,
            "opposing_evidence": opposing,
            "risk": risk,
            "missing_data": missing,
            "stance": thesis.stance
            if findings or thesis.stance == "insufficient_evidence"
            else "insufficient_evidence",
        }
    )


def _schema_check(thesis: Thesis) -> ValidationCheck:
    plan = thesis.plan
    unset = plan.entry is None or plan.invalidation is None or plan.target is None
    if unset and not plan.unset_reason:
        return ValidationCheck(
            name="schema",
            passed=False,
            detail="entry, invalidation or target is unset without unset_reason",
        )
    if thesis.provenance != "live" and not thesis.is_demonstration:
        return ValidationCheck(
            name="schema",
            passed=False,
            detail="non-live thesis must be labeled demonstration",
        )
    return ValidationCheck(name="schema", passed=True, detail=None)


def _feature_check(thesis: Thesis, known_feature_ids: set[UUID]) -> ValidationCheck:
    missing = [
        str(item.feature_id)
        for item in thesis.technical_findings
        if item.feature_id not in known_feature_ids
    ]
    if missing:
        return ValidationCheck(
            name="feature_ids_exist",
            passed=False,
            detail="unknown feature ids: " + ", ".join(missing),
        )
    return ValidationCheck(name="feature_ids_exist", passed=True, detail=None)


def _numeric_check(thesis: Thesis, feature_levels: dict[UUID, set[Decimal]]) -> ValidationCheck:
    referenced: set[Decimal] = set()
    for finding in thesis.technical_findings:
        referenced.update(feature_levels.get(finding.feature_id, set()))
    bad: list[str] = []
    for name, price in (
        ("entry", thesis.plan.entry),
        ("invalidation", thesis.plan.invalidation),
        ("target", thesis.plan.target),
    ):
        if price is not None and price not in referenced:
            bad.append(name)
    if bad:
        return ValidationCheck(
            name="numeric_crosscheck",
            passed=False,
            detail="prices do not match a referenced feature level: " + ", ".join(bad),
        )
    return ValidationCheck(name="numeric_crosscheck", passed=True, detail=None)


def _annotation_check(
    thesis: Thesis, calculations: dict[UUID, SavedCalculation] | None
) -> ValidationCheck:
    """Chart annotations and thesis findings must be the saved feature, not a new number."""
    if calculations is None:
        return ValidationCheck(name="annotation_crosscheck", passed=True, detail=None)
    bad: list[str] = []
    for finding in thesis.technical_findings:
        saved = calculations.get(finding.feature_id)
        expected = annotation_id_for(finding.feature_id)
        if saved is None or finding.annotation_id != expected or not _annotation_matches(saved):
            bad.append(str(finding.feature_id))
    if bad:
        return ValidationCheck(
            name="annotation_crosscheck",
            passed=False,
            detail="chart annotation does not match the saved calculation: " + ", ".join(bad),
        )
    return ValidationCheck(name="annotation_crosscheck", passed=True, detail=None)


def _annotation_matches(saved: SavedCalculation) -> bool:
    annotation = saved.annotation
    return (
        annotation.id == annotation_id_for(saved.feature_id)
        and annotation.feature_id == saved.feature_id
        and annotation.detector == saved.detector
        and annotation.calc_version == saved.calc_version
        and same_levels(annotation.levels, saved.levels)
    )


def _evidence_check(
    thesis: Thesis, known_source_ids: set[UUID], known_excerpt_ids: set[UUID]
) -> ValidationCheck:
    problems: list[str] = []
    problems.extend(
        _evidence_problems(
            thesis.supporting_evidence, "supporting", known_source_ids, known_excerpt_ids
        )
    )
    problems.extend(
        _evidence_problems(
            thesis.opposing_evidence, "opposing", known_source_ids, known_excerpt_ids
        )
    )
    if problems:
        return ValidationCheck(name="evidence_ids_exist", passed=False, detail="; ".join(problems))
    return ValidationCheck(name="evidence_ids_exist", passed=True, detail=None)


def _evidence_problems(
    items: list[EvidenceItem],
    expected: str,
    known_source_ids: set[UUID],
    known_excerpt_ids: set[UUID],
) -> list[str]:
    problems: list[str] = []
    for item in items:
        if item.source_id is not None and item.source_id not in known_source_ids:
            problems.append(f"source {item.source_id}")
        if item.excerpt_id is not None and item.excerpt_id not in known_excerpt_ids:
            problems.append(f"excerpt {item.excerpt_id}")
        if item.source_id is None and item.excerpt_id is None and not item.url:
            problems.append("unsourced claim")
        if item.stance != expected:
            problems.append(f"stance {item.stance} in {expected} list")
    return problems


def _risk_check(
    thesis: Thesis, tick_value: Decimal | None, point_value: Decimal | None
) -> ValidationCheck:
    risk = thesis.risk
    if risk is None:
        return ValidationCheck(name="risk_inputs", passed=True, detail=None)
    if risk.tick_value is not None and tick_value is not None and risk.tick_value != tick_value:
        return ValidationCheck(
            name="risk_inputs",
            passed=False,
            detail="tick_value does not match the listed contract",
        )
    if risk.point_value is not None and point_value is not None and risk.point_value != point_value:
        return ValidationCheck(
            name="risk_inputs",
            passed=False,
            detail="point_value does not match the listed contract",
        )
    return ValidationCheck(name="risk_inputs", passed=True, detail=None)


def _repair_plan(plan: TradePlan, known_prices: set[Decimal]) -> TradePlan:
    entry = plan.entry if plan.entry in known_prices else None
    invalidation = plan.invalidation if plan.invalidation in known_prices else None
    target = plan.target if plan.target in known_prices else None
    unset = entry is None or invalidation is None or target is None
    reason = plan.unset_reason
    if unset and not reason:
        reason = "Price did not match a computed feature level."
    return plan.model_copy(
        update={
            "entry": entry,
            "invalidation": invalidation,
            "target": target,
            "unset_reason": reason,
        }
    )


def _repair_evidence(
    items: list[EvidenceItem], known_source_ids: set[UUID], known_excerpt_ids: set[UUID]
) -> list[EvidenceItem]:
    kept: list[EvidenceItem] = []
    for item in items:
        source_ok = item.source_id is None or item.source_id in known_source_ids
        excerpt_ok = item.excerpt_id is None or item.excerpt_id in known_excerpt_ids
        if source_ok and excerpt_ok and (item.source_id or item.excerpt_id or item.url):
            kept.append(item)
    return kept


def attach_validation(thesis: Thesis, result: ValidationResult) -> Thesis:
    return thesis.model_copy(update={"validation": result})
