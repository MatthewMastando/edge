"""Reserve estimated spend before an external call and reconcile the actual cost after."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from trading_core.storage.repositories import analytics

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncEngine

    from trading_core.harness.limits import ResearchLimits

AI_CATEGORIES = "llm,search,fetch,source"


class BudgetExceededError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Reservation:
    ledger_id: int
    estimated: Decimal
    category: str


class BudgetService:
    def __init__(
        self,
        engine: AsyncEngine,
        limits: ResearchLimits,
        *,
        run_id: UUID,
        job_id: UUID,
    ) -> None:
        self._engine = engine
        self._limits = limits
        self._run_id = run_id
        self._job_id = job_id

    async def reserve(
        self, *, category: str, provider: str, estimate: Decimal, unit_type: str
    ) -> Reservation:
        limit = Decimal(0) if category == "market_data" else self._limits.monthly_ai_search_usd
        now = datetime.now(UTC)
        start, end = analytics.month_bounds(now)
        async with self._engine.begin() as conn:
            if category != "market_data":
                spent = await analytics.month_spend(
                    conn, start=start, end=end, categories=AI_CATEGORIES
                )
                if spent + estimate > limit:
                    msg = (
                        f"monthly AI/search ceiling of {limit} USD would be exceeded "
                        f"(committed {spent}, reserve {estimate})"
                    )
                    raise BudgetExceededError(msg)
            await analytics.upsert_budget(
                conn,
                category="ai_search" if category != "market_data" else "market_data",
                period_start=start,
                limit_usd=limit,
            )
            ledger_id = await analytics.insert_usage(
                conn,
                run_id=self._run_id,
                job_id=self._job_id,
                category=category,
                provider=provider,
                units=Decimal(1),
                unit_type=unit_type,
                reserved_cost_usd=estimate,
            )
        return Reservation(ledger_id=ledger_id, estimated=estimate, category=category)

    async def reconcile(self, reservation: Reservation, actual: Decimal) -> None:
        async with self._engine.begin() as conn:
            await analytics.reconcile_usage(conn, reservation.ledger_id, actual)
