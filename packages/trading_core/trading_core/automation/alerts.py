"""In-app alerts: new actionable research, material changes, or failures.

Failures and budget stops are recorded by the job runner. This module decides whether a
finished thesis is worth an alert. Neutral or insufficient research with no changed plan
does not notify.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pydantic import JsonValue

AlertKind = Literal["new_research", "material_change"]
_ACTIONABLE = frozenset({"bullish", "bearish"})


def decide_alert(
    current: dict[str, JsonValue], prior: dict[str, JsonValue] | None
) -> AlertKind | None:
    """``material_change`` wins when a frozen plan changed. Otherwise only actionable theses."""
    if prior is not None and _levels(current) != _levels(prior):
        return "material_change"
    if _actionable(current):
        return "new_research"
    return None


def _actionable(structured: dict[str, JsonValue]) -> bool:
    stance = structured.get("stance")
    entry = _plan(structured).get("entry")
    return stance in _ACTIONABLE and entry not in (None, "")


def _levels(structured: dict[str, JsonValue]) -> tuple[JsonValue, JsonValue, JsonValue, JsonValue]:
    plan = _plan(structured)
    return (
        structured.get("stance"),
        plan.get("entry"),
        plan.get("invalidation"),
        plan.get("target"),
    )


def _plan(structured: dict[str, JsonValue]) -> dict[str, JsonValue]:
    raw = structured.get("plan")
    if isinstance(raw, dict):
        return raw
    return {}
