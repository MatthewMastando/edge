"""Reserve estimated spend before an external call and reconcile the actual cost after."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from trading_core.storage.repositories import analytics

if TYPE_CHECKING:
    from uuid import UUID

    from pydantic import JsonValue
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

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
        run_id: UUID | None,
        job_id: UUID | None,
    ) -> None:
        self._engine = engine
        self._limits = limits
        self._run_id = run_id
        self._job_id = job_id

    async def reserve(
        self,
        *,
        category: str,
        provider: str,
        estimate: Decimal,
        unit_type: str,
        units: Decimal | None = None,
    ) -> Reservation:
        now = datetime.now(UTC)
        start, end = analytics.month_bounds(now)
        market = category == "market_data"
        budget_category = "market_data" if market else "ai_search"
        async with self._engine.begin() as conn:
            limit = await _ceiling(conn, budget_category, self._fallback(market))
            # Lock the monthly budget row before reading spend so two runs cannot both
            # pass the ceiling check and reserve past the limit.
            await analytics.upsert_budget(
                conn,
                category=budget_category,
                period_start=start,
                limit_usd=limit,
            )
            categories = "market_data" if market else AI_CATEGORIES
            spent = await analytics.month_spend(conn, start=start, end=end, categories=categories)
            # A zero market-data ceiling means record-only. AI/search always enforces.
            if (not market or limit > 0) and spent + estimate > limit:
                label = "market-data" if market else "AI/search"
                msg = (
                    f"monthly {label} ceiling of {limit} USD would be exceeded "
                    f"(committed {spent}, reserve {estimate})"
                )
                raise BudgetExceededError(msg)
            ledger_id = await analytics.insert_usage(
                conn,
                run_id=self._run_id,
                job_id=self._job_id,
                category=category,
                provider=provider,
                units=units if units is not None else Decimal(1),
                unit_type=unit_type,
                reserved_cost_usd=estimate,
            )
        return Reservation(ledger_id=ledger_id, estimated=estimate, category=category)

    def _fallback(self, market: bool) -> Decimal:
        if market:
            return self._limits.monthly_market_data_usd
        return self._limits.monthly_ai_search_usd

    async def reconcile(self, reservation: Reservation, actual: Decimal) -> None:
        async with self._engine.begin() as conn:
            await analytics.reconcile_usage(conn, reservation.ledger_id, actual)


async def _ceiling(conn: AsyncConnection, category: str, fallback: Decimal) -> Decimal:
    key = (
        "budget.market_data_monthly_usd"
        if category == "market_data"
        else "budget.ai_search_monthly_usd"
    )
    stored = await analytics.get_setting(conn, key)
    parsed = _stored_limit(stored)
    if parsed is None:
        return fallback
    return parsed


def _stored_limit(stored: dict[str, JsonValue] | None) -> Decimal | None:
    if stored is None:
        return None
    raw = stored.get("usd")
    if isinstance(raw, str):
        return Decimal(raw)
    return None
