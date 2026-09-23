"""Labels carried by every live result: source, coverage, and delay."""

from __future__ import annotations

from typing import Literal

from trading_core.domain.common import DomainModel, Provenance

FailureStatus = Literal["failed", "missing_credential", "rate_limited", "missing_coverage"]


class FeedLabel(DomainModel):
    """Honest description of one feed result. Fixture and recorded rows use the same shape."""

    source: str
    coverage: str
    delay: str
    provenance: Provenance

    def as_note(self) -> str:
        return f"source={self.source}; coverage={self.coverage}; delay={self.delay}"


class SourceFailure(RuntimeError):  # noqa: N818 — status vocabulary, not a generic Error
    """A source could not be read. Callers must surface this; they must not substitute data."""

    def __init__(
        self,
        *,
        source: str,
        coverage: str,
        delay: str,
        reason: str,
        status: FailureStatus = "failed",
    ) -> None:
        self.source = source
        self.coverage = coverage
        self.delay = delay
        self.reason = reason
        self.status: FailureStatus = status
        super().__init__(
            f"source={source}; coverage={coverage}; delay={delay}; status={status}; reason={reason}"
        )

    def label(self, *, provenance: Provenance = "live") -> FeedLabel:
        return FeedLabel(
            source=self.source,
            coverage=self.coverage,
            delay=self.delay,
            provenance=provenance,
        )


def missing_credential(source: str, env_name: str, *, coverage: str) -> SourceFailure:
    return SourceFailure(
        source=source,
        coverage=coverage,
        delay="not requested",
        reason=f"{env_name} is not set",
        status="missing_credential",
    )


def tool_feed(adapter: object, symbol: str) -> dict[str, str]:
    """Source, coverage, and delay for a tool or snapshot. Fixture rows stay labeled."""
    labeler = getattr(adapter, "feed_label", None)
    if callable(labeler):
        label = labeler(symbol)
        if isinstance(label, FeedLabel):
            return {
                "source": label.source,
                "coverage": label.coverage,
                "delay": label.delay,
                "provenance": label.provenance,
            }
    capabilities = getattr(adapter, "capabilities", None)
    provider = str(getattr(capabilities, "provider", "unknown"))
    provenance = str(getattr(capabilities, "provenance", "fixture"))
    coverage = getattr(capabilities, "coverage_note", None)
    delay = (
        "none; demonstration data has no exchange delay"
        if provenance != "live"
        else "not separately reported"
    )
    return {
        "source": provider,
        "coverage": str(coverage) if coverage else "unspecified",
        "delay": delay,
        "provenance": provenance,
    }
