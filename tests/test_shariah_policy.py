import json

import pytest

from src.reliability.shariah_policy import (
    ShariahPolicyError,
    apply_accounting_policy,
    build_policy_review_queue,
    load_shariah_policy,
    route_business_screen,
)


def _policy(decisions=None):
    return {
        "schema_version": 1,
        "policy_version": "draft-1",
        "decisions": decisions or {},
    }


def _review():
    return {
        "facts": {"total_debt": None, "interest_income": None},
        "candidates": {
            "lease_liabilities": {"value": 83.23, "pages": [3]},
            "cashflow_interest_income_adjustment": {"value": 224.0, "pages": [4]},
        },
    }


def test_pending_accounting_decision_does_not_promote_candidate():
    policy = _policy({
        "lease_liabilities_to_total_debt": {
            "status": "PENDING",
            "source_candidate": "lease_liabilities",
            "target_fact": "total_debt",
        }
    })

    result = apply_accounting_policy(_review(), policy)

    assert result["facts"]["total_debt"] is None
    assert result["policy_applications"] == []


def test_approved_decision_requires_authority_and_evidence():
    policy = _policy({
        "lease_liabilities_to_total_debt": {
            "status": "APPROVED",
            "source_candidate": "lease_liabilities",
            "target_fact": "total_debt",
        }
    })

    with pytest.raises(ShariahPolicyError, match="approval metadata"):
        apply_accounting_policy(_review(), policy)


def test_approved_decision_can_promote_candidate_with_audit_trail():
    policy = _policy({
        "lease_liabilities_to_total_debt": {
            "status": "APPROVED",
            "source_candidate": "lease_liabilities",
            "target_fact": "total_debt",
            "approved_by": "qualified-board",
            "evidence_uri": "file:///reviews/lease-ruling.pdf",
            "effective_from": "2026-07-11",
        }
    })

    result = apply_accounting_policy(_review(), policy)

    assert result["facts"]["total_debt"] == 83.23
    assert result["policy_applications"][0]["decision_id"] == "lease_liabilities_to_total_debt"
    assert result["policy_applications"][0]["policy_version"] == "draft-1"


@pytest.mark.parametrize(
    ("business_type", "route", "tradeable"),
    [
        ("CONVENTIONAL_BANK", "EXCLUDED_RIBA_BUSINESS", False),
        ("CONVENTIONAL_NBFC", "EXCLUDED_RIBA_BUSINESS", False),
        ("INSURER", "SPECIALIST_REVIEW", False),
        ("NON_FINANCIAL", "RATIO_SCREEN", None),
        (None, "UNKNOWN_BUSINESS", False),
    ],
)
def test_business_screen_routes_fail_closed(business_type, route, tradeable):
    result = route_business_screen(business_type)

    assert result == {"route": route, "tradeable": tradeable}


def test_policy_loader_rejects_unknown_status(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(_policy({"x": {"status": "MAYBE"}})))

    with pytest.raises(ShariahPolicyError, match="unsupported decision status"):
        load_shariah_policy(path)


def test_review_queue_exposes_missing_facts_and_relevant_pending_decisions():
    policy = _policy({
        "lease_liabilities_to_total_debt": {
            "status": "PENDING",
            "source_candidate": "lease_liabilities",
            "target_fact": "total_debt",
        },
        "unrelated": {
            "status": "PENDING",
            "source_candidate": "other_income",
            "target_fact": "interest_income",
        },
    })

    queue = build_policy_review_queue([{"symbol": "ABBOTINDIA", **_review()}], policy)

    assert queue == [{
        "symbol": "ABBOTINDIA",
        "missing_facts": ["interest_income", "total_debt"],
        "available_candidates": ["cashflow_interest_income_adjustment", "lease_liabilities"],
        "pending_decisions": ["lease_liabilities_to_total_debt"],
    }]
