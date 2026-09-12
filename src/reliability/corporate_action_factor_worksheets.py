"""Deterministic, non-authoritative corporate-action factor worksheets."""

from __future__ import annotations

import copy
import re
from datetime import datetime, time
from decimal import Context, Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
from typing import Mapping
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "corporate-action-factor-worksheet-v1"
FORMULA = (
    "TERP=(cum_rights_price*old_shares+issue_price*new_shares)"
    "/(old_shares+new_shares); factor=TERP/cum_rights_price"
)

_KOLKATA = ZoneInfo("Asia/Kolkata")
_QUANTUM = Decimal("0.000000000001")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_INPUT_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
_DECIMAL_TOKEN = rf"(?:{_NUMBER}|[+-]?(?:NAN|INFINITY))"
_TOKEN_END = r"(?![\w.])"
_CURRENCY = r"(?:RS\.?|INR|₹)"
_RIGHTS_LABEL = re.compile(r"\bRIGHTS?\b", re.IGNORECASE)
_RIGHTS_CLAUSE = re.compile(
    r"\bRIGHTS?\b(?P<body>.*?)(?=@|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_RATIO_BODY = re.compile(
    rf"\s*(?P<new>{_NUMBER}){_TOKEN_END}\s*:\s*"
    rf"(?P<old>{_NUMBER}){_TOKEN_END}\s*\Z",
    re.IGNORECASE,
)
_DIRECT_PRICE = re.compile(
    rf"@\s*(?:(?:ISSUE|OFFER)\s+PRICE\s*)?{_CURRENCY}\s*"
    rf"(?P<value>{_DECIMAL_TOKEN}|[A-Za-z]+){_TOKEN_END}",
    re.IGNORECASE,
)
_FACE_VALUE = re.compile(
    rf"\bFACE\s*VALUE(?:\s+OF)?\s*{_CURRENCY}\s*"
    rf"(?P<value>{_DECIMAL_TOKEN}){_TOKEN_END}",
    re.IGNORECASE,
)
_PREMIUM = re.compile(
    rf"\bPREMIUM\s*{_CURRENCY}\s*(?P<value>{_DECIMAL_TOKEN}){_TOKEN_END}",
    re.IGNORECASE,
)
_DIRECT_MARKER = re.compile(
    rf"@\s*(?:(?:ISSUE|OFFER)\s+PRICE\s*)?{_CURRENCY}",
    re.IGNORECASE,
)
_FACE_LABEL = re.compile(r"\bFACE\s*VALUE\b", re.IGNORECASE)
_FACE_VALUE_MARKER = re.compile(
    rf"\bFACE\s*VALUE(?:\s+OF)?\s*{_CURRENCY}",
    re.IGNORECASE,
)
_PREMIUM_LABEL = re.compile(r"\bPREMIUM\b", re.IGNORECASE)
_PREMIUM_MARKER = re.compile(rf"\bPREMIUM\s*{_CURRENCY}", re.IGNORECASE)
_TERM_CONNECTOR = re.compile(r"\s*(?:\+|PLUS|AND)\s*", re.IGNORECASE)
_CURRENCY_MARKER = re.compile(_CURRENCY, re.IGNORECASE)
_FULL_DIRECT_TERMS = re.compile(
    rf"\s*RIGHTS?\s+{_NUMBER}{_TOKEN_END}\s*:\s*"
    rf"{_NUMBER}{_TOKEN_END}\s*@\s*"
    rf"(?:(?:ISSUE|OFFER)\s+PRICE\s*)?{_CURRENCY}\s*"
    rf"{_DECIMAL_TOKEN}{_TOKEN_END}\s*(?:/-)?\s*\Z",
    re.IGNORECASE,
)
_FULL_FACE_PREMIUM_TERMS = re.compile(
    rf"\s*RIGHTS?\s+{_NUMBER}{_TOKEN_END}\s*:\s*"
    rf"{_NUMBER}{_TOKEN_END}\s*@\s*"
    rf"FACE\s*VALUE(?:\s+OF)?\s*{_CURRENCY}\s*"
    rf"{_DECIMAL_TOKEN}{_TOKEN_END}\s*(?:\+|PLUS|AND)\s*"
    rf"PREMIUM\s*{_CURRENCY}\s*{_DECIMAL_TOKEN}{_TOKEN_END}"
    rf"\s*(?:/-)?\s*\Z",
    re.IGNORECASE,
)
_REVIEW_FIELDS = {
    "review_id",
    "symbol",
    "action_type",
    "ex_date",
    "purpose",
    "reason",
}
_INPUT_FIELDS = {"value", "path", "sha256", "available_at"}
_SUPPORTED_ACTION_TYPES = {"RIGHTS", "MERGER", "DEMERGER"}
_PROHIBITED_AUTHORITY_FIELDS = {
    "adjustment_factor",
    "approval",
    "approved",
    "audit_authority",
    "canonical_decision",
    "decision",
    "reviewed_at",
    "reviewed_corporate_action_audit",
    "reviewer_id",
}


class FactorWorksheetError(ValueError):
    """A worksheet input cannot be used without weakening an integrity boundary."""


def _reject_authority(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise FactorWorksheetError("worksheet input keys must be strings")
            if key.lower() in _PROHIBITED_AUTHORITY_FIELDS:
                raise FactorWorksheetError("worksheet input cannot carry audit authority")
            _reject_authority(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_authority(nested)


def _parse_timestamp(value: str, *, label: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise FactorWorksheetError(f"{label} availability timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FactorWorksheetError(f"{label} availability timestamp must include an offset")
    return parsed


def _validate_review_row(review_row: Mapping[str, str]) -> tuple[dict[str, str], datetime]:
    if not isinstance(review_row, Mapping):
        raise FactorWorksheetError("review row must be a mapping")
    _reject_authority(review_row)
    if set(review_row) != _REVIEW_FIELDS:
        raise FactorWorksheetError("review row schema is invalid")
    if any(not isinstance(review_row[field], str) for field in _REVIEW_FIELDS):
        raise FactorWorksheetError("review row fields must be strings")

    row = {field: review_row[field] for field in sorted(_REVIEW_FIELDS)}
    if _SHA256.fullmatch(row["review_id"]) is None:
        raise FactorWorksheetError("review ID is invalid")
    if not row["symbol"] or not row["purpose"] or not row["reason"]:
        raise FactorWorksheetError("review identity fields cannot be blank")
    if row["action_type"] not in _SUPPORTED_ACTION_TYPES:
        raise FactorWorksheetError("review action type is unsupported")
    try:
        ex_date = datetime.strptime(row["ex_date"], "%Y-%m-%d").date()
    except ValueError as error:
        raise FactorWorksheetError("review ex-date is invalid") from error
    cutoff = datetime.combine(ex_date, time(hour=9, minute=15), tzinfo=_KOLKATA)
    return row, cutoff


def _validate_retained_inputs(
    retained_inputs: Mapping[str, object],
) -> tuple[dict[str, dict[str, str]], dict[str, datetime]]:
    if not isinstance(retained_inputs, Mapping):
        raise FactorWorksheetError("retained inputs must be a mapping")
    _reject_authority(retained_inputs)

    normalized: dict[str, dict[str, str]] = {}
    timestamps: dict[str, datetime] = {}
    for name in sorted(retained_inputs):
        if not isinstance(name, str) or _INPUT_NAME.fullmatch(name) is None:
            raise FactorWorksheetError("retained input name is invalid")
        source = retained_inputs[name]
        if not isinstance(source, Mapping) or set(source) != _INPUT_FIELDS:
            raise FactorWorksheetError(f"retained input binding is invalid: {name}")
        if any(not isinstance(source[field], str) for field in _INPUT_FIELDS):
            raise FactorWorksheetError(f"retained input fields must be strings: {name}")
        if (
            not source["path"]
            or _SHA256.fullmatch(source["sha256"]) is None
            or not source["available_at"]
        ):
            raise FactorWorksheetError(f"retained input binding is invalid: {name}")
        timestamps[name] = _parse_timestamp(source["available_at"], label=name)
        normalized[name] = {
            field: source[field]
            for field in ("value", "path", "sha256", "available_at")
        }
    return normalized, timestamps


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except DecimalException:
        return None


def _arithmetic_context(*values: Decimal) -> Context:
    finite = [value for value in values if value.is_finite()]
    integer_digits = [
        max(len(value.as_tuple().digits) + value.as_tuple().exponent, 1)
        for value in finite
    ]
    fractional_digits = [
        max(-value.as_tuple().exponent, 0)
        for value in finite
    ]
    precision = max(
        80,
        sum(len(value.as_tuple().digits) for value in finite) * 2 + 10,
        max(integer_digits, default=1) + max(fractional_digits, default=0) + 10,
    )
    return Context(prec=precision, rounding=ROUND_HALF_EVEN, traps=[])


def _parse_rights_terms(purpose: str) -> tuple[dict[str, str | None], list[str]]:
    reasons: list[str] = []
    rights_labels = list(_RIGHTS_LABEL.finditer(purpose))
    clauses = list(_RIGHTS_CLAUSE.finditer(purpose))
    ratio = (
        _RATIO_BODY.fullmatch(clauses[0].group("body"))
        if len(clauses) == 1
        else None
    )
    if len(rights_labels) > 1 or len(clauses) > 1:
        reasons.append("AMBIGUOUS_RIGHTS_RATIO")
        new_shares = None
        old_shares = None
    elif ratio is None:
        reasons.append(
            "MALFORMED_RIGHTS_RATIO" if ":" in purpose else "MISSING_RIGHTS_RATIO"
        )
        new_shares = None
        old_shares = None
    else:
        new_shares = ratio.group("new")
        old_shares = ratio.group("old")

    directs = list(_DIRECT_PRICE.finditer(purpose))
    faces = list(_FACE_VALUE.finditer(purpose))
    premiums = list(_PREMIUM.finditer(purpose))
    direct_markers = list(_DIRECT_MARKER.finditer(purpose))
    face_labels = list(_FACE_LABEL.finditer(purpose))
    face_markers = list(_FACE_VALUE_MARKER.finditer(purpose))
    premium_labels = list(_PREMIUM_LABEL.finditer(purpose))
    premium_markers = list(_PREMIUM_MARKER.finditer(purpose))
    currency_markers = list(_CURRENCY_MARKER.finditer(purpose))
    face_value = faces[0].group("value") if len(faces) == 1 else None
    premium_value = premiums[0].group("value") if len(premiums) == 1 else None
    issue_price: str | None = None
    issue_price_method: str | None = None

    ambiguous_price = (
        len(direct_markers) > 1
        or len(face_labels) > 1
        or len(premium_labels) > 1
        or (bool(direct_markers) and bool(face_labels or premium_labels))
        or (
            bool(direct_markers)
            and len(currency_markers) > 1
        )
        or (
            not direct_markers
            and bool(face_labels or premium_labels)
            and len(currency_markers) > len(face_labels) + len(premium_labels)
        )
    )
    malformed_price = (
        (bool(direct_markers) and len(directs) != len(direct_markers))
        or (bool(face_markers) and len(faces) != len(face_markers))
        or (bool(premium_markers) and len(premiums) != len(premium_markers))
    )

    if ambiguous_price:
        reasons.append("AMBIGUOUS_ISSUE_PRICE")
    elif malformed_price:
        reasons.append("MALFORMED_ISSUE_PRICE")
    elif len(directs) == 1:
        direct = directs[0]
        issue_price = direct.group("value")
        issue_price_method = "DIRECT"
        issue_decimal = _decimal(issue_price)
        if issue_decimal is None:
            reasons.append("MALFORMED_ISSUE_PRICE")
        elif not issue_decimal.is_finite():
            reasons.append("NONFINITE_ISSUE_PRICE")
        elif issue_decimal <= 0:
            reasons.append("NONPOSITIVE_ISSUE_PRICE")
    elif face_value is not None and premium_value is not None:
        connector = purpose[faces[0].end():premiums[0].start()]
        if faces[0].end() > premiums[0].start() or _TERM_CONNECTOR.fullmatch(connector) is None:
            reasons.append("AMBIGUOUS_ISSUE_PRICE")
            face_decimal = None
            premium_decimal = None
        else:
            face_decimal = _decimal(face_value)
            premium_decimal = _decimal(premium_value)
        if face_decimal is not None and premium_decimal is not None:
            if not face_decimal.is_finite() or not premium_decimal.is_finite():
                reasons.append("NONFINITE_ISSUE_PRICE")
            elif face_decimal <= 0:
                reasons.append("NONPOSITIVE_FACE_VALUE")
            elif premium_decimal <= 0:
                reasons.append("NONPOSITIVE_PREMIUM")
            else:
                with localcontext(_arithmetic_context(face_decimal, premium_decimal)):
                    combined_price = face_decimal + premium_decimal
                if not combined_price.is_finite():
                    reasons.append("NONFINITE_ISSUE_PRICE")
                elif combined_price <= 0:
                    reasons.append("NONPOSITIVE_ISSUE_PRICE")
                else:
                    issue_price = str(combined_price)
                    issue_price_method = "FACE_VALUE_PLUS_PREMIUM"
        elif "AMBIGUOUS_ISSUE_PRICE" not in reasons:
            reasons.append("MALFORMED_ISSUE_PRICE")
    elif premium_value is not None:
        reasons.append("MISSING_FACE_VALUE")
    elif face_value is not None:
        reasons.append("MISSING_PREMIUM")
    else:
        reasons.append("MISSING_ISSUE_PRICE")

    recognized_complete_form = (
        issue_price_method == "DIRECT"
        and _FULL_DIRECT_TERMS.fullmatch(purpose) is not None
    ) or (
        issue_price_method == "FACE_VALUE_PLUS_PREMIUM"
        and _FULL_FACE_PREMIUM_TERMS.fullmatch(purpose) is not None
    )
    structural_reasons = {
        "AMBIGUOUS_ISSUE_PRICE",
        "AMBIGUOUS_RIGHTS_RATIO",
        "MALFORMED_ISSUE_PRICE",
        "MALFORMED_RIGHTS_RATIO",
        "MISSING_RIGHTS_RATIO",
    }
    if (
        issue_price_method is not None
        and not recognized_complete_form
        and structural_reasons.isdisjoint(reasons)
    ):
        reasons.append("UNCONSUMED_RIGHTS_TERMS")

    return {
        "new_shares": new_shares,
        "old_shares": old_shares,
        "face_value": face_value,
        "premium": premium_value,
        "issue_price": issue_price,
        "issue_price_method": issue_price_method,
    }, reasons


def _append_once(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _manual_worksheet(
    *,
    row: Mapping[str, str],
    retained_inputs: Mapping[str, Mapping[str, str]],
    action_type: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "proposal_only": True,
        "review_id": row["review_id"],
        "queue_kind": "factor",
        "review_identity": {
            field: row[field]
            for field in ("symbol", "action_type", "ex_date", "purpose", "reason")
        },
        "retained_inputs": copy.deepcopy(dict(retained_inputs)),
        "parsed_terms": None,
        "calculation_inputs": None,
        "formula": None,
        "candidate_factor": None,
        "proposal_status": "MANUAL_REQUIRED",
        "manual_required_reasons": [
            f"{action_type}_FACTOR_MUST_BE_HUMAN_VERIFIED"
        ],
    }


def build_factor_worksheet(
    review_row: Mapping[str, str],
    *,
    retained_inputs: Mapping[str, object],
) -> dict[str, object]:
    """Build one deterministic factor proposal without granting review authority."""
    row, cutoff = _validate_review_row(review_row)
    inputs, timestamps = _validate_retained_inputs(retained_inputs)
    action_type = row["action_type"]

    if action_type in {"MERGER", "DEMERGER"}:
        return _manual_worksheet(
            row=row,
            retained_inputs=inputs,
            action_type=action_type,
        )

    parsed_terms, reasons = _parse_rights_terms(row["purpose"])
    terms_source = inputs.get("rights_terms")
    if terms_source is None:
        _append_once(reasons, "MISSING_RIGHTS_TERMS_SOURCE")
    else:
        if terms_source["value"] != row["purpose"]:
            raise FactorWorksheetError("retained rights terms do not match review identity")
        if timestamps["rights_terms"] >= cutoff:
            _append_once(reasons, "POST_CUTOFF_RIGHTS_TERMS")

    price_source = inputs.get("cum_rights_price")
    cum_rights_price: Decimal | None = None
    if price_source is None:
        _append_once(reasons, "MISSING_CUM_RIGHTS_PRICE")
    else:
        if timestamps["cum_rights_price"] >= cutoff:
            _append_once(reasons, "POST_CUTOFF_CUM_RIGHTS_PRICE")
        cum_rights_price = _decimal(price_source["value"])
        if cum_rights_price is None:
            _append_once(reasons, "MALFORMED_CUM_RIGHTS_PRICE")
        elif not cum_rights_price.is_finite():
            _append_once(reasons, "NONFINITE_CUM_RIGHTS_PRICE")
        elif cum_rights_price <= 0:
            _append_once(reasons, "NONPOSITIVE_CUM_RIGHTS_PRICE")

    calculation_inputs = {
        "new_shares": parsed_terms["new_shares"],
        "old_shares": parsed_terms["old_shares"],
        "issue_price": parsed_terms["issue_price"],
        "cum_rights_price": (
            price_source["value"] if price_source is not None else None
        ),
    }
    candidate_factor: str | None = None
    new_shares = (
        _decimal(parsed_terms["new_shares"])
        if parsed_terms["new_shares"] is not None
        else None
    )
    old_shares = (
        _decimal(parsed_terms["old_shares"])
        if parsed_terms["old_shares"] is not None
        else None
    )
    issue_price = (
        _decimal(parsed_terms["issue_price"])
        if parsed_terms["issue_price"] is not None
        else None
    )

    numeric_values = (new_shares, old_shares, issue_price)
    if any(value is not None and not value.is_finite() for value in numeric_values):
        _append_once(reasons, "NONFINITE_RIGHTS_TERMS")
    if (
        new_shares is not None
        and old_shares is not None
        and (new_shares <= 0 or old_shares <= 0)
    ):
        _append_once(reasons, "NONPOSITIVE_RIGHTS_RATIO")

    if (
        not reasons
        and new_shares is not None
        and old_shares is not None
        and issue_price is not None
        and cum_rights_price is not None
    ):
        try:
            with localcontext(_arithmetic_context(
                cum_rights_price,
                old_shares,
                issue_price,
                new_shares,
            )) as context:
                terp = (
                    cum_rights_price * old_shares + issue_price * new_shares
                ) / (old_shares + new_shares)
                factor = terp / cum_rights_price
                if not factor.is_finite():
                    _append_once(reasons, "NONFINITE_CANDIDATE_FACTOR")
                elif factor <= 0:
                    _append_once(reasons, "NONPOSITIVE_CANDIDATE_FACTOR")
                elif factor > 1:
                    _append_once(reasons, "CANDIDATE_FACTOR_ABOVE_ONE")
                else:
                    quantized_factor = factor.quantize(
                        _QUANTUM,
                        rounding=ROUND_HALF_EVEN,
                        context=context,
                    )
                    if not quantized_factor.is_finite():
                        _append_once(reasons, "UNREPRESENTABLE_CANDIDATE_FACTOR")
                    elif quantized_factor <= 0:
                        _append_once(
                            reasons,
                            "NONPOSITIVE_QUANTIZED_CANDIDATE_FACTOR",
                        )
                    elif quantized_factor > 1:
                        _append_once(
                            reasons,
                            "QUANTIZED_CANDIDATE_FACTOR_ABOVE_ONE",
                        )
                    else:
                        candidate_factor = format(quantized_factor, "f")
        except DecimalException:
            _append_once(reasons, "UNREPRESENTABLE_CANDIDATE_FACTOR")

    return {
        "schema_version": SCHEMA_VERSION,
        "proposal_only": True,
        "review_id": row["review_id"],
        "queue_kind": "factor",
        "review_identity": {
            field: row[field]
            for field in ("symbol", "action_type", "ex_date", "purpose", "reason")
        },
        "retained_inputs": copy.deepcopy(inputs),
        "parsed_terms": parsed_terms,
        "calculation_inputs": calculation_inputs,
        "formula": FORMULA,
        "candidate_factor": candidate_factor,
        "proposal_status": "AI_PROPOSED" if candidate_factor is not None else "MANUAL_REQUIRED",
        "manual_required_reasons": reasons,
    }
