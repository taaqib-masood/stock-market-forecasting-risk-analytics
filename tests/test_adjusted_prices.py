import copy

import pandas as pd
import pytest

from tests.corporate_action_test_support import (
    CONFIRMED_AVAILABLE_AT,
    EVIDENCE_PATH,
    EVIDENCE_SOURCE_URL,
    METHOD,
    REVIEWED_AT,
    REVIEWER_ID,
    issue_reviewed_factor_chain,
    rights_action,
)
from src.reliability.adjusted_prices import (
    CorporateActionError,
    adjust_ohlcv,
    apply_reviewed_factor_overrides,
)
from src.reliability.corporate_action_reviews import (
    CorporateActionReviewError,
    ReviewedFactorOverrides,
)


def _frame():
    return pd.DataFrame(
        {
            "Open": [98.0, 102.0, 51.0],
            "High": [101.0, 104.0, 53.0],
            "Low": [97.0, 99.0, 50.0],
            "Close": [100.0, 100.0, 52.0],
            "Volume": [1000.0, 1200.0, 2400.0],
        },
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )


def test_split_adjustment_is_deterministic_for_ohlcv():
    actions = [{
        "action_type": "SPLIT",
        "ex_date": "2024-01-03",
        "payload": {"purpose": "Face Value Split From Rs 10 Per Share To Rs 5 Per Share"},
    }]

    first = adjust_ohlcv(_frame(), actions)
    second = adjust_ohlcv(_frame(), actions)

    pd.testing.assert_frame_equal(first, second)
    assert first.loc["2024-01-02", "Close"] == 50.0
    assert first.loc["2024-01-02", "Volume"] == 2400.0
    assert first.loc["2024-01-03", "Close"] == 52.0


def test_dividend_adjusts_prior_prices_but_not_volume():
    actions = [{
        "action_type": "DIVIDEND",
        "ex_date": "2024-01-03",
        "payload": {"purpose": "Dividend - Rs 10 Per Share"},
    }]

    adjusted = adjust_ohlcv(_frame(), actions)

    assert adjusted.loc["2024-01-02", "Close"] == 90.0
    assert adjusted.loc["2024-01-02", "Volume"] == 1200.0


def test_combined_dividends_sum_all_explicit_cash_amounts():
    actions = [{
        "action_type": "DIVIDEND",
        "ex_date": "2024-01-03",
        "payload": {
            "purpose": "Final Dividend - Rs 20 Per Share / Special Dividend - Rs 10 Per Share"
        },
    }]

    adjusted = adjust_ohlcv(_frame(), actions)

    assert adjusted.loc["2024-01-02", "Close"] == 70.0


def test_unquantifiable_action_fails_closed():
    actions = [{
        "action_type": "DEMERGER",
        "ex_date": "2024-01-03",
        "payload": {"purpose": "Demerger"},
    }]

    with pytest.raises(CorporateActionError, match="DEMERGER"):
        adjust_ohlcv(_frame(), actions)


@pytest.mark.parametrize("provenance_case", ["missing", "partial", "blank", "extra"])
def test_raw_non_automatic_factor_is_rejected_regardless_of_provenance_shape(provenance_case):
    action = {
        "action_type": "DEMERGER",
        "ex_date": "2024-01-03",
        "payload": {"purpose": "Demerger", "adjustment_factor": 0.75},
    }
    complete = {
        "review_id": "review-1",
        "method": "Independent method",
        "evidence_path": "evidence/notice.txt",
        "evidence_sha256": "a" * 64,
        "evidence_source_url": "https://www.nseindia.com/notice",
        "confirmed_available_at": "2024-01-02T10:00:00Z",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2024-01-02T12:00:00Z",
    }
    if provenance_case == "partial":
        action["payload"]["review_provenance"] = {"review_id": "review-1"}
    elif provenance_case == "blank":
        complete["reviewer_id"] = "  "
        action["payload"]["review_provenance"] = complete
    elif provenance_case == "extra":
        complete["unexpected"] = "not allowed"
        action["payload"]["review_provenance"] = complete

    with pytest.raises(CorporateActionError, match="unreviewed raw factor"):
        adjust_ohlcv(_frame(), [action])


def test_direct_factor_conversion_failures_are_corporate_action_errors():
    action = {
        "action_type": "DEMERGER",
        "ex_date": "2024-01-03",
        "payload": {
            "purpose": "Demerger",
            "adjustment_factor": "not-a-number",
            "review_provenance": {
                "review_id": "review-1",
                "method": "Independent method",
                "evidence_path": "evidence/notice.txt",
                "evidence_sha256": "a" * 64,
                "evidence_source_url": "https://www.nseindia.com/notice",
                "confirmed_available_at": "2024-01-02T10:00:00Z",
                "reviewer_id": "reviewer-1",
                "reviewed_at": "2024-01-02T12:00:00Z",
            },
        },
    }

    with pytest.raises(CorporateActionError, match="factor"):
        adjust_ohlcv(_frame(), [action])


def test_raw_non_automatic_factor_with_shape_valid_provenance_is_not_reviewed():
    action = {
        "action_type": "DEMERGER",
        "ex_date": "2024-01-03",
        "payload": {
            "purpose": "Demerger",
            "adjustment_factor": 0.75,
            "review_provenance": {
                "review_id": "review-1",
                "method": "Independent method",
                "evidence_path": "evidence/notice.txt",
                "evidence_sha256": "a" * 64,
                "evidence_source_url": "https://www.nseindia.com/notice",
                "confirmed_available_at": "2024-01-02T10:00:00Z",
                "reviewer_id": "reviewer-1",
                "reviewed_at": "2024-01-02T12:00:00Z",
            },
        },
    }

    with pytest.raises(CorporateActionError, match="DEMERGER"):
        adjust_ohlcv(_frame(), [action])


def test_apply_reviewed_factor_overrides_rejects_raw_override_rows():
    action = {
        "symbol": "TCS",
        "action_type": "RIGHTS",
        "ex_date": "2024-01-03",
        "payload": {"purpose": "Rights 1:4 @ Premium Rs 10"},
    }

    with pytest.raises(CorporateActionError, match="verified audit artifact"):
        apply_reviewed_factor_overrides([action], [{"adjustment_factor": 0.75}])


def _forged_override_rows():
    return ({
        "review_id": "review-1",
        "symbol": "TCS",
        "action_type": "RIGHTS",
        "ex_date": "2024-01-03",
        "purpose": "Rights 1:4 @ Premium Rs 10",
        "adjustment_factor": 0.75,
        "method": "Independent method",
        "evidence_path": "evidence/notice.txt",
        "evidence_sha256": "b" * 64,
        "evidence_source_url": "https://www.nseindia.com/notice",
        "confirmed_available_at": "2024-01-02T10:00:00Z",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2024-01-02T12:00:00Z",
    },)


def test_reviewed_factor_overrides_cannot_be_constructed_directly():
    with pytest.raises(CorporateActionReviewError, match="verified audit"):
        ReviewedFactorOverrides(
            audit_sha256="a" * 64,
            _rows=_forged_override_rows(),
        )


def test_apply_reviewed_factor_overrides_rejects_unissued_wrapper():
    action = {
        "symbol": "TCS",
        "action_type": "RIGHTS",
        "ex_date": "2024-01-03",
        "payload": {"purpose": "Rights 1:4 @ Premium Rs 10"},
    }
    forged = object.__new__(ReviewedFactorOverrides)
    object.__setattr__(forged, "_audit_sha256", "a" * 64)
    object.__setattr__(forged, "_rows", _forged_override_rows())

    with pytest.raises(CorporateActionError, match="verified audit artifact"):
        apply_reviewed_factor_overrides([action], forged)


def test_verified_overrides_are_deterministic_across_source_and_action_ordering(
    tmp_path,
):
    actions = [
        rights_action(symbol="TCS"),
        rights_action(symbol="INFY", purpose="Rights 2:5 @ Premium Rs 20"),
    ]
    forward = issue_reviewed_factor_chain(
        tmp_path,
        actions=actions,
        factors=["0.75", "0.80"],
        name="forward",
    )
    reverse = issue_reviewed_factor_chain(
        tmp_path,
        actions=list(reversed(actions)),
        factors=["0.75", "0.80"],
        name="reverse",
    )

    first = adjust_ohlcv(
        _frame(),
        list(forward.actions),
        reviewed_factor_overrides=forward.capability,
    )
    second = adjust_ohlcv(
        _frame(),
        list(reverse.actions),
        reviewed_factor_overrides=reverse.capability,
    )

    pd.testing.assert_frame_equal(first, second)
    assert forward.capability.rows == reverse.capability.rows


def test_adjustment_does_not_mutate_caller_frame_actions_or_nested_data(
    tmp_path,
):
    chain = issue_reviewed_factor_chain(tmp_path)
    frame = _frame()
    actions = [
        copy.deepcopy(chain.actions[0]),
        {
            "symbol": "TCS",
            "action_type": "SPLIT",
            "ex_date": "2024-01-03",
            "payload": {
                "purpose": (
                    "Face Value Split From Rs 10 Per Share To Rs 5 Per Share"
                ),
                "source": {"kind": "nse_corporate_actions"},
            },
            "exchange_fields": {"series": "EQ"},
        },
    ]
    frame_before = frame.copy(deep=True)
    actions_before = copy.deepcopy(actions)
    capability_rows_before = chain.capability.rows

    adjusted = adjust_ohlcv(
        frame,
        actions,
        reviewed_factor_overrides=chain.capability,
    )

    pd.testing.assert_frame_equal(frame, frame_before)
    assert actions == actions_before
    assert chain.capability.rows == capability_rows_before
    assert adjusted is not frame
    assert actions[0] is not chain.actions[0]
    assert actions[0]["payload"] is not chain.actions[0]["payload"]


def test_duplicate_targeted_action_identity_is_rejected(tmp_path):
    chain = issue_reviewed_factor_chain(tmp_path)
    action = copy.deepcopy(chain.actions[0])

    with pytest.raises(CorporateActionError, match="multiple actions"):
        apply_reviewed_factor_overrides(
            [action, copy.deepcopy(action)],
            chain.capability,
        )


@pytest.mark.parametrize(
    "factors",
    [
        pytest.param(["0.75", "0.75"], id="equal"),
        pytest.param(["0.75", "0.80"], id="conflicting"),
    ],
)
def test_duplicate_semantic_override_identity_is_rejected(tmp_path, factors):
    action = rights_action()
    chain = issue_reviewed_factor_chain(
        tmp_path,
        actions=[action, copy.deepcopy(action)],
        factors=factors,
    )

    with pytest.raises(CorporateActionError, match="duplicate override identity"):
        apply_reviewed_factor_overrides([action], chain.capability)


def test_unused_issued_override_is_rejected(tmp_path):
    chain = issue_reviewed_factor_chain(tmp_path)
    unrelated = rights_action(symbol="INFY")

    with pytest.raises(
        CorporateActionError,
        match="does not match exactly one action",
    ):
        apply_reviewed_factor_overrides([unrelated], chain.capability)


@pytest.mark.parametrize(
    "field,value",
    [
        pytest.param("symbol", ["TCS"], id="symbol"),
        pytest.param("action_type", ["RIGHTS"], id="action-type"),
        pytest.param("ex_date", "03-Jan-2024", id="ex-date"),
        pytest.param("purpose", ["Rights"], id="purpose"),
    ],
)
def test_malformed_action_identity_is_rejected(tmp_path, field, value):
    chain = issue_reviewed_factor_chain(tmp_path)
    malformed = copy.deepcopy(chain.actions[0])
    if field == "purpose":
        malformed["payload"]["purpose"] = value
    else:
        malformed[field] = value

    with pytest.raises(CorporateActionError):
        apply_reviewed_factor_overrides([malformed], chain.capability)


def test_issued_capability_preserves_complete_authoritative_provenance_and_rows(
    tmp_path,
):
    chain = issue_reviewed_factor_chain(tmp_path)
    authoritative = chain.reviewed_report["reviewed_factor_overrides"][0]
    issued = chain.capability.rows[0]
    action = copy.deepcopy(chain.actions[0])
    action_before = copy.deepcopy(action)

    assert chain.capability.rows == (authoritative,)
    assert issued == {
        "review_id": authoritative["review_id"],
        "symbol": "TCS",
        "action_type": "RIGHTS",
        "ex_date": "2024-01-03",
        "purpose": "Rights 1:4 @ Premium Rs 10",
        "adjustment_factor": 0.75,
        "method": METHOD,
        "evidence_path": EVIDENCE_PATH,
        "evidence_sha256": authoritative["evidence_sha256"],
        "evidence_source_url": EVIDENCE_SOURCE_URL,
        "confirmed_available_at": CONFIRMED_AVAILABLE_AT,
        "reviewer_id": REVIEWER_ID,
        "reviewed_at": REVIEWED_AT,
    }

    adjusted = adjust_ohlcv(
        _frame(),
        [action],
        reviewed_factor_overrides=chain.capability,
    )

    assert adjusted.loc["2024-01-02", "Close"] == 75.0
    assert action == action_before
    assert action["payload"]["source"] == {
        "kind": "nse_corporate_actions",
        "symbol": "TCS",
    }
    assert action["exchange_fields"] == {
        "series": "EQ",
        "record_date": "2024-01-03",
    }
    issued["method"] = "caller mutation"
    assert chain.capability.rows[0]["method"] == METHOD


@pytest.mark.parametrize(
    "factor",
    [
        pytest.param("Infinity", id="infinity"),
        pytest.param("not-a-number", id="non-numeric"),
        pytest.param("1e1000000", id="oversized"),
    ],
)
def test_authoritative_review_rejects_invalid_factor(tmp_path, factor):
    with pytest.raises(CorporateActionReviewError):
        issue_reviewed_factor_chain(tmp_path, factors=[factor])
