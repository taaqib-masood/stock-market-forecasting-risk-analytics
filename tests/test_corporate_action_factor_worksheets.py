from __future__ import annotations

import copy
from decimal import Inexact, Rounded, localcontext

import pytest

from src.reliability.corporate_action_factor_worksheets import (
    FORMULA,
    FactorWorksheetError,
    build_factor_worksheet,
)


REVIEW_ID = "a" * 64
TERMS_SHA256 = "1" * 64
PRICE_SHA256 = "2" * 64


def _review(purpose: str, *, action_type: str = "RIGHTS") -> dict[str, str]:
    return {
        "review_id": REVIEW_ID,
        "symbol": "ABC",
        "action_type": action_type,
        "ex_date": "2024-01-31",
        "purpose": purpose,
        "reason": "reviewed adjustment factor required",
    }


def _inputs(
    purpose: str,
    *,
    cum_rights_price: str | None = "100",
    terms_available_at: str = "2024-01-15T10:00:00Z",
    price_available_at: str = "2024-01-30T10:00:00Z",
) -> dict[str, object]:
    values: dict[str, object] = {
        "rights_terms": {
            "value": purpose,
            "path": "data/reliability/actions-2024-01.json",
            "sha256": TERMS_SHA256,
            "available_at": terms_available_at,
        },
    }
    if cum_rights_price is not None:
        values["cum_rights_price"] = {
            "value": cum_rights_price,
            "path": "data/reliability/prices/ABC-2024-01-30.json",
            "sha256": PRICE_SHA256,
            "available_at": price_available_at,
        }
    return values


@pytest.mark.parametrize(
    ("purpose", "expected"),
    [
        (
            "Rights 588:1000@ Premium Rs 2/-",
            {
                "new_shares": "588",
                "old_shares": "1000",
                "face_value": None,
                "premium": "2",
                "issue_price": None,
                "issue_price_method": None,
            },
        ),
        (
            "Rights 1 : 4 @ Rs. 80/-",
            {
                "new_shares": "1",
                "old_shares": "4",
                "face_value": None,
                "premium": None,
                "issue_price": "80",
                "issue_price_method": "DIRECT",
            },
        ),
        (
            "Rights 1.5 : 10.0 @ Rs 80.25",
            {
                "new_shares": "1.5",
                "old_shares": "10.0",
                "face_value": None,
                "premium": None,
                "issue_price": "80.25",
                "issue_price_method": "DIRECT",
            },
        ),
        (
            "Rights 1:4 @ Face Value Rs 10 + Premium Rs 70",
            {
                "new_shares": "1",
                "old_shares": "4",
                "face_value": "10",
                "premium": "70",
                "issue_price": "80",
                "issue_price_method": "FACE_VALUE_PLUS_PREMIUM",
            },
        ),
    ],
)
def test_rights_terms_preserve_raw_decimal_strings(purpose, expected):
    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(purpose),
    )

    assert worksheet["parsed_terms"] == expected


def test_malformed_ratio_is_manual_required_without_factor():
    purpose = "Rights 1::4 @ Rs 80"

    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(purpose),
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert worksheet["manual_required_reasons"] == ["MALFORMED_RIGHTS_RATIO"]


@pytest.mark.parametrize(
    ("purpose", "expected_reason"),
    [
        ("Rights issue @ Rs 80", "MISSING_RIGHTS_RATIO"),
        ("Rights 1:4", "MISSING_ISSUE_PRICE"),
        ("Rights 588:1000@ Premium Rs 2/-", "MISSING_FACE_VALUE"),
        ("Rights 1:4 @ Face Value Rs 10", "MISSING_PREMIUM"),
        ("Rights 1:4 @ Face Value + Premium Rs 70", "MISSING_FACE_VALUE"),
    ],
)
def test_incomplete_rights_terms_are_manual_required(purpose, expected_reason):
    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(purpose),
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert expected_reason in worksheet["manual_required_reasons"]


def test_complete_rights_inputs_calculate_quantized_terp_factor():
    purpose = "Rights 1:4 @ Rs 80"

    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(purpose),
    )

    assert worksheet["schema_version"] == "corporate-action-factor-worksheet-v1"
    assert worksheet["proposal_only"] is True
    assert worksheet["proposal_status"] == "AI_PROPOSED"
    assert worksheet["formula"] == FORMULA == (
        "TERP=(cum_rights_price*old_shares+issue_price*new_shares)"
        "/(old_shares+new_shares); factor=TERP/cum_rights_price"
    )
    assert worksheet["calculation_inputs"] == {
        "new_shares": "1",
        "old_shares": "4",
        "issue_price": "80",
        "cum_rights_price": "100",
    }
    assert worksheet["candidate_factor"] == "0.960000000000"
    assert worksheet["manual_required_reasons"] == []


@pytest.mark.parametrize(
    ("price", "available_at", "expected_reason"),
    [
        (None, "2024-01-30T10:00:00Z", "MISSING_CUM_RIGHTS_PRICE"),
        ("100", "2024-01-31T03:46:00Z", "POST_CUTOFF_CUM_RIGHTS_PRICE"),
        ("not-a-number", "2024-01-30T10:00:00Z", "MALFORMED_CUM_RIGHTS_PRICE"),
        ("NaN", "2024-01-30T10:00:00Z", "NONFINITE_CUM_RIGHTS_PRICE"),
        ("0", "2024-01-30T10:00:00Z", "NONPOSITIVE_CUM_RIGHTS_PRICE"),
        ("-1", "2024-01-30T10:00:00Z", "NONPOSITIVE_CUM_RIGHTS_PRICE"),
    ],
)
def test_missing_post_cutoff_or_invalid_prices_require_manual_review(
    price,
    available_at,
    expected_reason,
):
    purpose = "Rights 1:4 @ Rs 80"

    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(
            purpose,
            cum_rights_price=price,
            price_available_at=available_at,
        ),
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert expected_reason in worksheet["manual_required_reasons"]


@pytest.mark.parametrize(
    ("purpose", "expected_reason"),
    [
        ("Rights 1:4 @ Rs -400", "NONPOSITIVE_ISSUE_PRICE"),
        ("Rights 1:4 @ Rs -500", "NONPOSITIVE_ISSUE_PRICE"),
        ("Rights 1:4 @ Rs 200", "CANDIDATE_FACTOR_ABOVE_ONE"),
        ("Rights 0:4 @ Rs 80", "NONPOSITIVE_RIGHTS_RATIO"),
        ("Rights 1:0 @ Rs 80", "NONPOSITIVE_RIGHTS_RATIO"),
    ],
)
def test_zero_negative_or_above_one_cases_never_emit_factor(
    purpose,
    expected_reason,
):
    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(purpose),
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert expected_reason in worksheet["manual_required_reasons"]


@pytest.mark.parametrize(
    ("purpose", "expected_reason"),
    [
        ("Rights 1:4 @ Rs 0", "NONPOSITIVE_ISSUE_PRICE"),
        ("Rights 1:4 @ Rs -1", "NONPOSITIVE_ISSUE_PRICE"),
        ("Rights 1:4 @ Rs NaN", "NONFINITE_ISSUE_PRICE"),
        ("Rights 1:4 @ Rs Infinity", "NONFINITE_ISSUE_PRICE"),
        ("Rights 1:4 @ Rs eighty", "MALFORMED_ISSUE_PRICE"),
    ],
)
def test_invalid_issue_price_never_emits_factor(purpose, expected_reason):
    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(purpose),
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert expected_reason in worksheet["manual_required_reasons"]


@pytest.mark.parametrize(
    ("purpose", "expected_reason"),
    [
        (
            "Rights 1:4 @ Face Value Rs -10 + Premium Rs 10",
            "NONPOSITIVE_FACE_VALUE",
        ),
        (
            "Rights 1:4 @ Face Value Rs 10 + Premium Rs -20",
            "NONPOSITIVE_PREMIUM",
        ),
        (
            "Rights 1:4 @ Face Value Rs NaN + Premium Rs 2",
            "NONFINITE_ISSUE_PRICE",
        ),
        (
            "Rights 1:4 @ Face Value Rs Infinity + Premium Rs 2",
            "NONFINITE_ISSUE_PRICE",
        ),
    ],
)
def test_face_plus_premium_requires_finite_positive_components_and_sum(
    purpose,
    expected_reason,
):
    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(purpose),
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert expected_reason in worksheet["manual_required_reasons"]


@pytest.mark.parametrize(
    "purpose",
    [
        "Rights 1:4 @ Face Value Rs -10 + Premium Rs 20",
        "Rights 1:4 @ Face Value Rs 0 + Premium Rs 80",
    ],
)
def test_face_plus_premium_requires_each_component_to_be_strictly_positive(
    purpose,
):
    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(purpose),
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert "NONPOSITIVE_FACE_VALUE" in worksheet["manual_required_reasons"]


def test_face_plus_premium_addition_ignores_ambient_decimal_context():
    purpose = "Rights 1:4 @ Face Value Rs 10.123 + Premium Rs 70.456"

    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        worksheet = build_factor_worksheet(
            _review(purpose),
            retained_inputs=_inputs(purpose),
        )

    assert worksheet["parsed_terms"]["issue_price"] == "80.579"
    assert worksheet["proposal_status"] == "AI_PROPOSED"
    assert worksheet["candidate_factor"] == "0.961158000000"


@pytest.mark.parametrize(
    ("purpose", "expected_reason"),
    [
        ("Rights 1:4junk @ Rs 80x", "MALFORMED_RIGHTS_RATIO"),
        ("Rights 1:4 @ Rs 80x", "MALFORMED_ISSUE_PRICE"),
        ("Rights 1:4 @ Rs 80.5.6", "MALFORMED_ISSUE_PRICE"),
        (
            "Rights 1:4 and Rights 2:5 @ Rs 80",
            "AMBIGUOUS_RIGHTS_RATIO",
        ),
        ("Rights 1:4 @ Rs 80 @ Rs 90", "AMBIGUOUS_ISSUE_PRICE"),
        (
            "Rights 1:4 @ Rs 80; Face Value Rs 10 + Premium Rs 70",
            "AMBIGUOUS_ISSUE_PRICE",
        ),
        (
            "Rights 1:4 @ Face Value Rs 10x + Premium Rs 70",
            "MALFORMED_ISSUE_PRICE",
        ),
    ],
)
def test_rights_parser_rejects_partial_or_ambiguous_terms(
    purpose,
    expected_reason,
):
    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(purpose),
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert expected_reason in worksheet["manual_required_reasons"]


@pytest.mark.parametrize(
    "purpose",
    [
        "Rights 1:4-5 @ Rs 80",
        "Rights 1:4/5 @ Rs 80",
        "Rights 1:4 @ Rs 80 or Rs 90",
        "Rights 1:4 @ Rs 80, Rs 90",
    ],
)
def test_rights_parser_rejects_unconsumed_ratio_or_price_terms(purpose):
    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(purpose),
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert worksheet["manual_required_reasons"]


def test_factor_that_rounds_to_zero_is_manual_required():
    purpose = (
        "Rights 1:0.00000000000000000001 "
        "@ Rs 0.00000000000000000001"
    )

    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(purpose),
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert "NONPOSITIVE_QUANTIZED_CANDIDATE_FACTOR" in (
        worksheet["manual_required_reasons"]
    )


@pytest.mark.parametrize("action_type", ["MERGER", "DEMERGER"])
def test_mergers_and_demergers_never_infer_factor(action_type):
    purpose = "Scheme ratio 3:2 and discovered price Rs 123.45"
    retained = {
        "scheme_document": {
            "value": purpose,
            "path": "data/reliability/evidence/scheme.pdf",
            "sha256": "3" * 64,
            "available_at": "2024-01-15T10:00:00Z",
        },
    }

    worksheet = build_factor_worksheet(
        _review(purpose, action_type=action_type),
        retained_inputs=retained,
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert worksheet["formula"] is None
    assert worksheet["parsed_terms"] is None
    assert worksheet["manual_required_reasons"] == [
        f"{action_type}_FACTOR_MUST_BE_HUMAN_VERIFIED"
    ]


def test_every_retained_input_is_bound_to_path_hash_and_availability():
    purpose = "Rights 1:4 @ Rs 80"
    retained = _inputs(purpose)

    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=retained,
    )

    assert worksheet["retained_inputs"] == retained
    assert set(worksheet["retained_inputs"]) == {
        "cum_rights_price",
        "rights_terms",
    }


def test_post_cutoff_terms_source_requires_manual_review():
    purpose = "Rights 1:4 @ Rs 80"

    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=_inputs(
            purpose,
            terms_available_at="2024-01-31T03:46:00Z",
        ),
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert "POST_CUTOFF_RIGHTS_TERMS" in worksheet["manual_required_reasons"]


def test_missing_terms_source_requires_manual_review():
    purpose = "Rights 1:4 @ Rs 80"
    retained = _inputs(purpose)
    del retained["rights_terms"]

    worksheet = build_factor_worksheet(
        _review(purpose),
        retained_inputs=retained,
    )

    assert worksheet["proposal_status"] == "MANUAL_REQUIRED"
    assert worksheet["candidate_factor"] is None
    assert "MISSING_RIGHTS_TERMS_SOURCE" in worksheet["manual_required_reasons"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda source: source.pop("path"),
        lambda source: source.update(sha256="not-a-hash"),
        lambda source: source.update(available_at="yesterday"),
        lambda source: source.update(extra="not-allowed"),
    ],
)
def test_malformed_retained_input_bindings_fail_closed(mutation):
    purpose = "Rights 1:4 @ Rs 80"
    retained = _inputs(purpose)
    mutation(retained["rights_terms"])

    with pytest.raises(FactorWorksheetError):
        build_factor_worksheet(
            _review(purpose),
            retained_inputs=retained,
        )


def test_authority_fields_are_rejected_recursively():
    purpose = "Rights 1:4 @ Rs 80"
    retained = _inputs(purpose)
    retained["rights_terms"]["decision"] = "APPROVED"

    with pytest.raises(FactorWorksheetError, match="authority"):
        build_factor_worksheet(
            _review(purpose),
            retained_inputs=retained,
        )


def test_review_identity_must_be_factor_queue_shape():
    purpose = "Rights 1:4 @ Rs 80"
    review = _review(purpose)
    review["decision"] = "APPROVED"

    with pytest.raises(FactorWorksheetError):
        build_factor_worksheet(review, retained_inputs=_inputs(purpose))


def test_output_is_deterministic_and_does_not_mutate_inputs():
    purpose = "Rights 1:4 @ Rs 80"
    review = _review(purpose)
    retained = _inputs(purpose)
    original_review = copy.deepcopy(review)
    original_retained = copy.deepcopy(retained)

    first = build_factor_worksheet(review, retained_inputs=retained)
    second = build_factor_worksheet(review, retained_inputs=retained)

    assert first == second
    assert review == original_review
    assert retained == original_retained
    assert "decision" not in first
    assert "adjustment_factor" not in first
    assert "audit_authority" not in first
