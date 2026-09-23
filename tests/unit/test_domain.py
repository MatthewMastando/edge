from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from trading_core.domain import CONTRACT_MODELS, JOB_TERMINAL_STATES, JOB_TRANSITIONS, Bar, Job
from trading_core.domain.thesis import TradePlan


def _bar(**overrides: object) -> Bar:
    base: dict[str, object] = {
        "instrument_id": uuid4(),
        "contract_code": "6EZ6",
        "timeframe": "5m",
        "origin_time": datetime(2026, 8, 31, 17, 0, tzinfo=timezone(timedelta(hours=-5))),
        "origin_tz": "America/Chicago",
        "open": Decimal("1.17250"),
        "high": Decimal("1.17260"),
        "low": Decimal("1.17245"),
        "close": Decimal("1.17255"),
        "volume": Decimal(48),
        "data_revision": "fixture-1.0.0-s1-deadbeef",
        "provenance": "fixture",
    }
    base.update(overrides)
    return Bar.model_validate(base)


def test_decimals_serialize_as_exact_strings() -> None:
    bar = _bar()
    payload = json.loads(bar.model_dump_json())
    assert payload["open"] == "1.17250"
    assert payload["volume"] == "48"
    assert Bar.model_validate(payload).open == Decimal("1.17250")


def test_datetimes_normalize_to_utc_and_keep_original_tz() -> None:
    bar = _bar()
    assert bar.origin_time.tzinfo == UTC
    assert bar.origin_time.hour == 22
    assert bar.origin_tz == "America/Chicago"


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _bar(origin_time=datetime(2026, 8, 31, 17, 0))


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _bar(unexpected=1)


def test_models_are_frozen() -> None:
    bar = _bar()
    with pytest.raises(ValidationError):
        bar.close = Decimal(1)  # type: ignore[misc]


def test_job_state_machine_constants_agree() -> None:
    states = set(Job.model_fields["state"].annotation.__args__)  # type: ignore[union-attr]
    assert states == {
        "queued",
        "running",
        "partial",
        "completed",
        "failed",
        "cancelled",
        "budget_exceeded",
    }
    assert set(JOB_TRANSITIONS) == states
    for terminal in JOB_TERMINAL_STATES:
        assert JOB_TRANSITIONS[terminal] == frozenset()
    assert "queued" in JOB_TRANSITIONS["running"], "lease expiry must requeue"


def test_trade_plan_can_be_explicitly_unset() -> None:
    plan = TradePlan(unset_reason="insufficient evidence")
    assert plan.entry is None
    assert plan.model_dump()["unset_reason"] == "insufficient evidence"


def test_every_contract_model_has_a_json_schema() -> None:
    for model in CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["title"] == model.__name__
        assert schema.get("additionalProperties") is False
