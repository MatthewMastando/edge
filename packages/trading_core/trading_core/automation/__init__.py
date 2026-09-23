"""Schedules, TA triggers, alerts and the hypothesis ledger.

Research jobs are created here. Nothing in this package submits broker orders.
"""

from trading_core.automation.alerts import decide_alert
from trading_core.automation.rules import TriggerDecision, trigger_decision
from trading_core.automation.schedule import next_occurrence

__all__ = [
    "TriggerDecision",
    "decide_alert",
    "next_occurrence",
    "trigger_decision",
]
