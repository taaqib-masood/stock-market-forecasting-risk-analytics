import pytest

from src.reliability.pdf_financial_evidence import (
    PdfEvidenceError,
    build_pdf_review,
    reconcile_pdf_reviews,
)


def _review(reviewer="analyst-a", **overrides):
    values = {
        "symbol": "ABBOTINDIA",
        "period_end": "2024-03-31",
        "available_at": "2024-05-09T13:06:35Z",
        "source_sha256": "a" * 64,
        "source_file": "abbot.pdf",
        "reviewer": reviewer,
        "unit": "INR crore",
        "facts": {
            "total_assets": 5193.49,
            "total_debt": None,
            "total_revenue": 5848.91,
            "interest_income": None,
        },
        "page_references": {
            "total_assets": [3],
            "total_revenue": [2],
        },
        "candidates": {
            "lease_liabilities": {"value": 83.23, "pages": [3]},
            "cashflow_interest_income_adjustment": {"value": 224.0, "pages": [4]},
        },
    }
    values.update(overrides)
    return build_pdf_review(**values)


POLICY = {
    "policy_version": "test-1",
    "authorized_data_reviewers": ["analyst-a", "analyst-b"],
}


def test_single_pdf_review_is_never_tradeable():
    review = _review()

    assert review["status"] == "single_review"
    assert review["tradeable"] is False


def test_two_matching_independent_reviews_reconcile_known_facts():
    facts = {
        "total_assets": 5193.49,
        "total_debt": 0.0,
        "total_revenue": 5848.91,
        "interest_income": 224.0,
    }

    result = reconcile_pdf_reviews(
        _review(facts=facts),
        _review(reviewer="analyst-b", facts=facts),
        policy=POLICY,
    )

    assert result["status"] == "reconciled"
    assert result["tradeable"] is True
    assert result["debt_to_assets"] == pytest.approx(0.0)
    assert result["interest_income_ratio"] == pytest.approx(224.0 / 5848.91)
    assert result["reviewers"] == ["analyst-a", "analyst-b"]


def test_missing_required_fact_remains_blocked_after_two_reviews():
    result = reconcile_pdf_reviews(_review(), _review(reviewer="analyst-b"), policy=POLICY)

    assert result["status"] == "incomplete"
    assert result["tradeable"] is False
    assert set(result["missing_facts"]) == {"interest_income", "total_debt"}


def test_disputed_values_fail_closed():
    second_facts = {
        "total_assets": 5000.0,
        "total_debt": None,
        "total_revenue": 5848.91,
        "interest_income": None,
    }

    with pytest.raises(PdfEvidenceError, match="fact disagreement: total_assets"):
        reconcile_pdf_reviews(
            _review(), _review(reviewer="analyst-b", facts=second_facts), policy=POLICY
        )


def test_same_reviewer_cannot_self_reconcile():
    with pytest.raises(PdfEvidenceError, match="independent reviewers"):
        reconcile_pdf_reviews(_review(), _review(), policy=POLICY)


def test_unregistered_reviewer_cannot_reconcile():
    with pytest.raises(PdfEvidenceError, match="unauthorized reviewer"):
        reconcile_pdf_reviews(
            _review(), _review(reviewer="unknown"), policy=POLICY
        )
