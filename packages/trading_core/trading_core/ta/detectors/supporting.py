"""Swing pivots, liquidity pools, ATR, RSI, VWAP, session levels and correlation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from trading_core.ta.constants import ATR_PERIOD, CALC_VERSION, RSI_PERIOD
from trading_core.ta.correlation import aligned_return_correlation
from trading_core.ta.detectors.common import (
    bar_draft,
    bind,
    finish,
    price_level,
    require_count,
    value_details,
    with_rolls,
)
from trading_core.ta.envelope import FeatureDraft, decimal_str, time_str
from trading_core.ta.interfaces import DetectorInput, DetectorOutput, InsufficientDataError
from trading_core.ta.parsing import as_object_list, param_optional_time
from trading_core.ta.series import PreparedSeries, bar_close_time, contract_of
from trading_core.ta.session_levels import detect_session_levels, session_has_overnight
from trading_core.ta.swings import detect_pools, detect_swings
from trading_core.ta.vwap import vwap_points
from trading_core.ta.wilder import atr_by_index, require_no_missing, rsi_by_index

if TYPE_CHECKING:
    from pydantic import JsonValue

    from trading_core.domain.common import CalcVersion
    from trading_core.domain.ta import DetectorName


class SwingPivotDetector:
    @property
    def name(self) -> DetectorName:
        return "swing_pivot"

    @property
    def calc_version(self) -> CalcVersion:
        return CALC_VERSION

    def default_parameters(self) -> dict[str, JsonValue]:
        return with_rolls()

    def run(self, data: DetectorInput) -> DetectorOutput:
        params, prepared = bind(data, self.default_parameters())
        require_count(prepared, 7, "swing pivots")
        drafts: list[FeatureDraft] = []
        for swing in detect_swings(prepared):
            bar = prepared.bars[swing.index]
            levels = []
            if swing.is_high:
                levels.append(price_level("swing_high", bar.high))
            if swing.is_low:
                levels.append(price_level("swing_low", bar.low))
            drafts.append(
                FeatureDraft(
                    direction="neutral",
                    session=data.session,
                    levels=levels,
                    state="confirmed",
                    origin_time=swing.origin_time,
                    origin_tz=swing.origin_tz,
                    confirmation_time=swing.confirmation_time,
                    confirmation_tz=bar.origin_tz,
                    contract_code=swing.contract_code,
                    details={
                        "index": swing.index,
                        "confirmation_index": swing.confirmation_index,
                        "is_high": swing.is_high,
                        "is_low": swing.is_low,
                    },
                )
            )
        return finish(
            name=self.name,
            data=data,
            prepared=prepared,
            params=params,
            drafts=drafts,
            warnings=[],
        )


class LiquidityPoolDetector:
    @property
    def name(self) -> DetectorName:
        return "liquidity_pool"

    @property
    def calc_version(self) -> CalcVersion:
        return CALC_VERSION

    def default_parameters(self) -> dict[str, JsonValue]:
        return with_rolls()

    def run(self, data: DetectorInput) -> DetectorOutput:
        params, prepared = bind(data, self.default_parameters())
        require_count(prepared, 4, "liquidity pools")
        drafts: list[FeatureDraft] = []
        for pool in detect_pools(prepared, prepared.tick):
            origin = prepared.bars[pool.origin_index]
            confirm = prepared.bars[pool.confirmation_index]
            formed = prepared.bars[pool.formed_index]
            name = "equal_high" if pool.side == "high" else "equal_low"
            drafts.append(
                FeatureDraft(
                    direction="neutral",
                    session=data.session,
                    levels=[price_level(name, pool.level)],
                    state="confirmed",
                    origin_time=origin.origin_time,
                    origin_tz=origin.origin_tz,
                    confirmation_time=bar_close_time(confirm),
                    confirmation_tz=confirm.origin_tz,
                    contract_code=pool.contract_code,
                    details={
                        "side": pool.side,
                        "level": decimal_str(pool.level),
                        "formed_at": time_str(formed.origin_time),
                        "origin_adjusted": pool.origin_adjusted,
                        "members": list(pool.members),
                        "confirmation_index": pool.confirmation_index,
                    },
                )
            )
        return finish(
            name=self.name, data=data, prepared=prepared, params=params, drafts=drafts, warnings=[]
        )


class _WilderDetector:
    def __init__(self, name: DetectorName) -> None:
        self._name = name

    @property
    def name(self) -> DetectorName:
        return self._name

    @property
    def calc_version(self) -> CalcVersion:
        return CALC_VERSION

    def default_parameters(self) -> dict[str, JsonValue]:
        return with_rolls()

    def run(self, data: DetectorInput) -> DetectorOutput:
        params, prepared = bind(data, self.default_parameters())
        require_no_missing(prepared, self._name.upper())
        period = ATR_PERIOD if self._name == "atr" else RSI_PERIOD
        values = _wilder_values(prepared, self._name, period)
        drafts = [
            bar_draft(
                prepared.bars[index],
                session=data.session,
                direction="neutral",
                state="confirmed",
                levels=[],
                details=value_details(index, values[index]),
            )
            for index in sorted(values)
        ]
        warnings: list[str] = []
        if "roll" in prepared.gaps:
            warnings.append("Wilder smoothing restarted after a contract roll")
        return finish(
            name=self.name,
            data=data,
            prepared=prepared,
            params=params,
            drafts=drafts,
            warnings=warnings,
        )


def _wilder_values(prepared: PreparedSeries, name: str, period: int) -> dict[int, Decimal]:
    if name == "atr":
        return atr_by_index(prepared, period=period, split_on=frozenset({"roll"}))
    return rsi_by_index(prepared, period=period, split_on=frozenset({"roll"}))


class AtrDetector(_WilderDetector):
    def __init__(self) -> None:
        super().__init__("atr")


class RsiDetector(_WilderDetector):
    def __init__(self) -> None:
        super().__init__("rsi")


class VwapDetector:
    @property
    def name(self) -> DetectorName:
        return "vwap"

    @property
    def calc_version(self) -> CalcVersion:
        return CALC_VERSION

    def default_parameters(self) -> dict[str, JsonValue]:
        return with_rolls({"anchor_time": ""})

    def run(self, data: DetectorInput) -> DetectorOutput:
        params, prepared = bind(data, self.default_parameters())
        anchor = param_optional_time(params, "anchor_time")
        trades = None if data.trades is None else list(data.trades.trades)
        points = vwap_points(prepared, data.calendar, trades, anchor)
        session = "anchored" if anchor is not None else data.session
        drafts = [
            bar_draft(
                prepared.bars[point.index],
                session=session,
                direction="neutral",
                state="confirmed",
                levels=[price_level("vwap", point.value)],
                details={
                    "index": point.index,
                    "value": decimal_str(point.value),
                    "source": point.source,
                },
            )
            for point in points
        ]
        return finish(
            name=self.name, data=data, prepared=prepared, params=params, drafts=drafts, warnings=[]
        )


class SessionLevelsDetector:
    @property
    def name(self) -> DetectorName:
        return "session_levels"

    @property
    def calc_version(self) -> CalcVersion:
        return CALC_VERSION

    def default_parameters(self) -> dict[str, JsonValue]:
        return with_rolls()

    def run(self, data: DetectorInput) -> DetectorOutput:
        params, prepared = bind(data, self.default_parameters())
        warnings: list[str] = []
        if not session_has_overnight(data.calendar):
            warnings.append("overnight levels are unavailable on a calendar with no separate RTH")
        found = detect_session_levels(prepared, data.calendar)
        if not found:
            warnings.append("no completed session window in this snapshot")
        drafts: list[FeatureDraft] = []
        for item in found:
            high_name, low_name = ("pdh", "pdl") if item.kind == "rth" else ("onh", "onl")
            drafts.append(
                FeatureDraft(
                    direction="neutral",
                    session=item.kind,
                    levels=[
                        price_level(high_name, item.high),
                        price_level(low_name, item.low),
                    ],
                    state="confirmed",
                    origin_time=item.origin_time,
                    origin_tz=item.timezone,
                    confirmation_time=item.confirmation_time,
                    confirmation_tz=item.timezone,
                    contract_code=item.contract_code,
                    details={
                        "kind": item.kind,
                        "session_day": item.session_day.isoformat(),
                        "high": decimal_str(item.high),
                        "low": decimal_str(item.low),
                        "high_time": time_str(item.high_time),
                        "low_time": time_str(item.low_time),
                    },
                )
            )
        return finish(
            name=self.name,
            data=data,
            prepared=prepared,
            params=params,
            drafts=drafts,
            warnings=warnings,
        )


class CorrelationDetector:
    @property
    def name(self) -> DetectorName:
        return "correlation"

    @property
    def calc_version(self) -> CalcVersion:
        return CALC_VERSION

    def default_parameters(self) -> dict[str, JsonValue]:
        return with_rolls({"other_bars": [], "other_instrument_id": ""})

    def run(self, data: DetectorInput) -> DetectorOutput:
        params, prepared = bind(data, self.default_parameters())
        other_id = params["other_instrument_id"]
        if not isinstance(other_id, str) or not other_id:
            msg = "correlation requires other_instrument_id"
            raise ValueError(msg)
        right = _other_closes(params)
        if not right:
            msg = "correlation requires other_bars"
            raise InsufficientDataError(msg)
        left = [(bar.origin_time, bar.close) for bar in prepared.bars]
        coefficient, count = aligned_return_correlation(left, right)
        origin = prepared.bars[0]
        confirm = prepared.bars[-1]
        draft = FeatureDraft(
            direction="neutral",
            session=data.session,
            levels=[],
            state="confirmed",
            origin_time=origin.origin_time,
            origin_tz=origin.origin_tz,
            confirmation_time=bar_close_time(confirm),
            confirmation_tz=confirm.origin_tz,
            contract_code=contract_of(origin),
            details={
                "correlation": decimal_str(coefficient),
                "n": count,
                "method": "sample_pearson",
                "other_instrument_id": other_id,
            },
        )
        return finish(
            name=self.name,
            data=data,
            prepared=prepared,
            params=params,
            drafts=[draft],
            warnings=[],
        )


def _other_closes(params: dict[str, JsonValue]) -> list[tuple[datetime, Decimal]]:
    rows = as_object_list(params["other_bars"], "other_bars")
    parsed: list[tuple[datetime, Decimal]] = []
    for row in rows:
        raw_time = row.get("origin_time")
        raw_close = row.get("close")
        if not isinstance(raw_time, str) or not isinstance(raw_close, str):
            msg = "other_bars entries need origin_time and close strings"
            raise ValueError(msg)
        try:
            instant = datetime.fromisoformat(raw_time)
        except ValueError as exc:
            msg = "other_bars origin_time must be ISO-8601"
            raise ValueError(msg) from exc
        if instant.tzinfo is None:
            msg = "other_bars origin_time must include a timezone"
            raise ValueError(msg)
        try:
            close = Decimal(raw_close)
        except InvalidOperation as exc:
            msg = "other_bars close must be a decimal string"
            raise ValueError(msg) from exc
        parsed.append((instant.astimezone(UTC), close))
    return parsed
