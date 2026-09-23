"""A retrieved or failed source, before it is stored with an evidence id."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from trading_core.domain.common import DomainModel, Provenance, UtcDatetime
from trading_core.labeling import FeedLabel, SourceFailure
from trading_core.research.interfaces import SourceKind

if TYPE_CHECKING:
    from datetime import datetime

HitStatus = Literal["ok", "failed", "rate_limited", "missing_coverage"]


class ResearchHit(DomainModel):
    kind: SourceKind
    label: FeedLabel
    title: str
    text: str
    url: str | None = None
    publisher: str
    published_at: UtcDatetime | None = None
    retrieved_at: UtcDatetime
    status: HitStatus = "ok"
    error: str | None = None
    external: bool = False

    def labeled_text(self) -> str:
        prefix = self.label.as_note()
        body = self.text if not self.error else f"{self.text} {self.error}"
        return f"{prefix}. {body}".strip()[:4000]


def failure_hit(
    kind: SourceKind,
    exc: SourceFailure,
    *,
    retrieved_at: datetime,
    publisher: str,
    provenance: Provenance = "live",
) -> ResearchHit:
    return ResearchHit(
        kind=kind,
        label=exc.label(provenance=provenance),
        title=f"{exc.source} unavailable",
        text=exc.reason,
        url=None,
        publisher=publisher,
        retrieved_at=retrieved_at,
        status="failed" if exc.status == "missing_credential" else exc.status,
        error=exc.reason,
        external=False,
    )
