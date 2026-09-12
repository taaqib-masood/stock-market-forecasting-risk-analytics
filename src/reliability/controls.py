"""Operational controls shared by release and execution paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Tuple


@dataclass(frozen=True)
class ControlDecision:
    """Immutable result of the signal risk, halal, and data-control checks."""

    allowed: bool
    hard_failures: Tuple[str, ...]
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ControlInput:
    """Point-in-time facts used to decide whether a new entry is permitted."""

    evaluated_at: datetime
    data_as_of: datetime
    halal_tradeable: bool | None
    portfolio_drawdown: float
    gross_exposure: float
    sector_exposure: float
    max_pairwise_correlation: float
    drift_alert: bool
    delivery_rate: float
    delivery_sample_size: int
    unresolved_corporate_actions: bool


@dataclass(frozen=True)
class ControlPolicy:
    """Hard entry-control thresholds used by the live and shadow paths."""

    max_data_age_hours: float = 48.0
    max_drawdown: float = 0.15
    max_gross_exposure: float = 0.80
    max_sector_exposure: float = 0.30
    max_pairwise_correlation: float = 0.80
    min_delivery_rate: float = 0.995
    min_delivery_samples: int = 20


def evaluate_controls(control_input: ControlInput, policy: ControlPolicy) -> ControlDecision:
    """Evaluate all hard entry controls and fail closed on any violation."""
    failures: list[str] = []
    evaluated_at = control_input.evaluated_at
    data_as_of = control_input.data_as_of
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)
    if data_as_of.tzinfo is None:
        data_as_of = data_as_of.replace(tzinfo=timezone.utc)
    if evaluated_at - data_as_of > timedelta(hours=policy.max_data_age_hours):
        failures.append("STALE_DATA")
    if control_input.halal_tradeable is None:
        failures.append("HALAL_UNKNOWN")
    elif control_input.halal_tradeable is False:
        failures.append("HALAL_BLOCKED")
    if control_input.portfolio_drawdown > policy.max_drawdown:
        failures.append("DRAWDOWN_LIMIT")
    if control_input.gross_exposure > policy.max_gross_exposure:
        failures.append("GROSS_EXPOSURE_LIMIT")
    if control_input.sector_exposure > policy.max_sector_exposure:
        failures.append("SECTOR_CONCENTRATION")
    if control_input.max_pairwise_correlation > policy.max_pairwise_correlation:
        failures.append("CORRELATION_LIMIT")
    if control_input.drift_alert:
        failures.append("STRATEGY_DRIFT")
    if control_input.delivery_sample_size < policy.min_delivery_samples:
        failures.append("DELIVERY_HISTORY_INSUFFICIENT")
    elif control_input.delivery_sample_size > 0 and control_input.delivery_rate < policy.min_delivery_rate:
        failures.append("DELIVERY_SLO")
    if control_input.unresolved_corporate_actions:
        failures.append("UNRESOLVED_CORPORATE_ACTION")
    return ControlDecision(allowed=not failures, hard_failures=tuple(failures))


def operational_kill_switch_active() -> bool:
    """Return whether operators have explicitly paused outbound actions."""
    return os.environ.get("BORO_OPERATIONAL_KILL_SWITCH", "").strip().lower() in {
        "1", "true", "yes", "on", "active",
    }
