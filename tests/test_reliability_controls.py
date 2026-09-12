from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.reliability.controls import (
    ControlInput,
    ControlPolicy,
    evaluate_controls,
)


NOW = datetime(2024, 7, 1, 4, 0, tzinfo=timezone.utc)


def _safe_input():
    return ControlInput(
        evaluated_at=NOW,
        data_as_of=NOW - timedelta(hours=4),
        halal_tradeable=True,
        portfolio_drawdown=0.04,
        gross_exposure=0.40,
        sector_exposure=0.20,
        max_pairwise_correlation=0.40,
        drift_alert=False,
        delivery_rate=1.0,
        delivery_sample_size=100,
        unresolved_corporate_actions=False,
    )


@pytest.mark.parametrize(
    "changed,reason",
    [
        ({"data_as_of": NOW - timedelta(hours=49)}, "STALE_DATA"),
        ({"halal_tradeable": None}, "HALAL_UNKNOWN"),
        ({"halal_tradeable": False}, "HALAL_BLOCKED"),
        ({"portfolio_drawdown": 0.16}, "DRAWDOWN_LIMIT"),
        ({"gross_exposure": 0.81}, "GROSS_EXPOSURE_LIMIT"),
        ({"sector_exposure": 0.31}, "SECTOR_CONCENTRATION"),
        ({"max_pairwise_correlation": 0.81}, "CORRELATION_LIMIT"),
        ({"drift_alert": True}, "STRATEGY_DRIFT"),
        ({"delivery_rate": 0.994}, "DELIVERY_SLO"),
        ({"unresolved_corporate_actions": True}, "UNRESOLVED_CORPORATE_ACTION"),
    ],
)
def test_each_hard_control_blocks_new_entries(changed, reason):
    decision = evaluate_controls(replace(_safe_input(), **changed), ControlPolicy())

    assert decision.allowed is False
    assert reason in decision.hard_failures


def test_safe_portfolio_is_allowed():
    decision = evaluate_controls(_safe_input(), ControlPolicy())

    assert decision.allowed is True
    assert decision.hard_failures == ()


def test_insufficient_delivery_history_fails_closed_for_public_policy():
    decision = evaluate_controls(
        replace(_safe_input(), delivery_sample_size=5),
        ControlPolicy(min_delivery_samples=20),
    )

    assert decision.allowed is False
    assert "DELIVERY_HISTORY_INSUFFICIENT" in decision.hard_failures


def test_shadow_policy_can_collect_initial_delivery_history():
    decision = evaluate_controls(
        replace(_safe_input(), delivery_sample_size=0, delivery_rate=0.0),
        ControlPolicy(min_delivery_samples=0),
    )

    assert decision.allowed is True
