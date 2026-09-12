"""Deterministic, fail-closed OHLCV corporate-action adjustments."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from datetime import date
from numbers import Real
import re
from typing import Any, Iterable

import pandas as pd

from src.reliability.corporate_action_reviews import (
    ReviewedFactorOverrides,
    is_verified_reviewed_factor_overrides,
)


class CorporateActionError(ValueError):
    """Raised when a visible price-impacting action cannot be quantified safely."""


PRICE_COLUMNS = ["Open", "High", "Low", "Close"]
NON_PRICE_PURPOSES = (
    "ANNUAL GENERAL MEETING",
    "EXTRA ORDINARY GENERAL MEETING",
    "BOOK CLOSURE",
    "INTEREST PAYMENT",
)

_OVERRIDE_IDENTITY_FIELDS = ("symbol", "action_type", "ex_date", "purpose")
_NON_AUTOMATIC_ACTIONS = {"RIGHTS", "MERGER", "DEMERGER"}
_REVIEW_PROVENANCE_FIELDS = (
    "review_id",
    "method",
    "evidence_path",
    "evidence_sha256",
    "evidence_source_url",
    "confirmed_available_at",
    "reviewer_id",
    "reviewed_at",
)


def _frame_timestamp(value: Any, index: pd.DatetimeIndex) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if index.tz is None and timestamp.tz is not None:
        return timestamp.tz_convert("UTC").tz_localize(None)
    if index.tz is not None and timestamp.tz is None:
        return timestamp.tz_localize(index.tz)
    return timestamp


def _numbers(text: str) -> list[float]:
    return [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))]


def _dividend_amounts(text: str) -> list[float]:
    return [
        float(value) for value in re.findall(
            r"DIVIDEND.{0,50}?(?:RS|RE)\.?[^\d]{0,6}(\d+(?:\.\d+)?)",
            text.replace(",", ""),
            re.I,
        )
    ]


def _action_factor(
    action: dict[str, Any],
    frame: pd.DataFrame,
    reviewed_factor: float | None = None,
) -> tuple[float, bool]:
    action_type = str(action.get("action_type", "OTHER")).upper()
    payload = action.get("payload") or {}
    if not isinstance(payload, dict):
        raise CorporateActionError("action payload is malformed")
    purpose = str(payload.get("purpose", ""))
    if action_type in _NON_AUTOMATIC_ACTIONS:
        if reviewed_factor is None:
            if "adjustment_factor" in payload:
                raise CorporateActionError(f"unreviewed raw factor for {action_type}")
            raise CorporateActionError(f"unsupported {action_type} action: {purpose}")
        return reviewed_factor, False

    return automatic_action_factor(action, frame)


def automatic_action_factor(
    action: dict[str, Any],
    frame: pd.DataFrame | None = None,
) -> tuple[float, bool]:
    """Derive an automatic action factor solely from published terms or cash."""
    action_type = str(action.get("action_type", "OTHER")).upper()
    payload = action.get("payload") or {}
    if not isinstance(payload, dict):
        raise CorporateActionError("action payload is malformed")
    purpose = str(payload.get("purpose", ""))

    if action_type == "BONUS":
        match = re.search(r"BONUS[^\d]*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", purpose, re.I)
        if not match:
            raise CorporateActionError(f"cannot quantify BONUS action: {purpose}")
        new, held = map(float, match.groups())
        return held / (held + new), True

    if action_type == "SPLIT":
        match = re.search(
            r"FROM\s+(?:RS\.?|INR)?\s*(\d+(?:\.\d+)?).*?TO\s+(?:RS\.?|INR)?\s*(\d+(?:\.\d+)?)",
            purpose,
            re.I,
        )
        if not match:
            raise CorporateActionError(f"cannot quantify SPLIT action: {purpose}")
        old_face_value, new_face_value = map(float, match.groups())
        if old_face_value <= 0 or not 0 < new_face_value < old_face_value:
            raise CorporateActionError(f"invalid SPLIT terms: {purpose}")
        return new_face_value / old_face_value, True

    if action_type == "DIVIDEND":
        if frame is None:
            raise CorporateActionError("DIVIDEND factor requires a price frame")
        values = _dividend_amounts(purpose)
        if not values:
            raise CorporateActionError(f"cannot quantify DIVIDEND action: {purpose}")
        ex_date = _frame_timestamp(action["ex_date"], frame.index)
        prior = frame.loc[frame.index < ex_date, "Close"]
        if prior.empty:
            raise CorporateActionError(f"DIVIDEND on {ex_date.date()} has no prior close")
        amount = sum(values)
        factor = (float(prior.iloc[-1]) - amount) / float(prior.iloc[-1])
        if not 0 < factor <= 1:
            raise CorporateActionError(f"invalid DIVIDEND factor for {purpose}")
        return factor, False

    if action_type == "OTHER" and any(term in purpose.upper() for term in NON_PRICE_PURPOSES):
        return 1.0, False
    raise CorporateActionError(f"unsupported {action_type} action: {purpose}")


def _override_identity(override: dict[str, Any]) -> tuple[str, str, str, str]:
    if not isinstance(override, dict):
        raise CorporateActionError("reviewed override identity is malformed")
    missing = [field for field in _OVERRIDE_IDENTITY_FIELDS if field not in override]
    if missing:
        raise CorporateActionError("reviewed override identity is malformed")

    symbol = override["symbol"]
    action_type = override["action_type"]
    ex_date = override["ex_date"]
    purpose = override["purpose"]
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (symbol, action_type, ex_date, purpose)
    ):
        raise CorporateActionError("reviewed override identity is malformed")
    try:
        parsed_ex_date = date.fromisoformat(ex_date)
    except ValueError as error:
        raise CorporateActionError("reviewed override identity is malformed") from error
    if parsed_ex_date.isoformat() != ex_date:
        raise CorporateActionError("reviewed override identity is malformed")
    return symbol, action_type.upper(), ex_date, purpose


def _action_identity(action: dict[str, Any]) -> tuple[str, str, str, str]:
    if not isinstance(action, dict) or not isinstance(action.get("payload"), dict):
        raise CorporateActionError("action identity is malformed")
    payload = action["payload"]
    symbol = action.get("symbol")
    action_type = action.get("action_type")
    ex_date = action.get("ex_date")
    purpose = payload.get("purpose")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (symbol, action_type, ex_date, purpose)
    ):
        raise CorporateActionError("action identity is malformed")
    try:
        parsed_ex_date = date.fromisoformat(ex_date)
    except ValueError as error:
        raise CorporateActionError("action identity is malformed") from error
    if parsed_ex_date.isoformat() != ex_date:
        raise CorporateActionError("action identity is malformed")
    return symbol, action_type.upper(), ex_date, purpose


def _validate_override(
    override: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, float, dict[str, str]]:
    identity = _override_identity(override)
    for field in _REVIEW_PROVENANCE_FIELDS:
        if field not in override:
            raise CorporateActionError("reviewed override provenance is missing")
        value = override[field]
        if not isinstance(value, str) or not value.strip():
            if field in {"method", "reviewer_id"}:
                raise CorporateActionError(f"reviewed override {field} is blank")
            raise CorporateActionError("reviewed override provenance is missing")

    factor = override.get("adjustment_factor")
    if isinstance(factor, bool) or not isinstance(factor, Real):
        raise CorporateActionError("reviewed adjustment factor is invalid")
    try:
        factor = float(factor)
    except (TypeError, ValueError, OverflowError) as error:
        raise CorporateActionError("reviewed adjustment factor is invalid") from error
    if not math.isfinite(factor) or not 0 < factor <= 1:
        raise CorporateActionError("reviewed adjustment factor is invalid")

    provenance = {field: override[field] for field in _REVIEW_PROVENANCE_FIELDS}
    return identity, provenance["review_id"], factor, provenance


@dataclass(frozen=True)
class _AppliedReviewedFactorOverrides:
    factors_by_identity: dict[tuple[str, str, str, str], float]


def apply_reviewed_factor_overrides(
    actions: Iterable[dict[str, Any]],
    overrides: ReviewedFactorOverrides | None,
) -> _AppliedReviewedFactorOverrides:
    """Validate an audit-bound factor overlay against its exact action targets."""
    if overrides is not None and not is_verified_reviewed_factor_overrides(overrides):
        raise CorporateActionError("reviewed overrides require a verified audit artifact")
    action_copies = copy.deepcopy(list(actions))
    override_rows = [] if overrides is None else list(overrides.rows)
    action_matches: dict[tuple[str, str, str, str], list[int]] = {}
    if override_rows:
        for index, action in enumerate(action_copies):
            action_type = str(action.get("action_type", "")).upper()
            if action_type not in _NON_AUTOMATIC_ACTIONS:
                continue
            identity = _action_identity(action)
            action_matches.setdefault(identity, []).append(index)

    validated = []
    review_ids: set[str] = set()
    identities: set[tuple[str, str, str, str]] = set()
    for override in override_rows:
        identity, review_id, factor, provenance = _validate_override(override)
        if review_id in review_ids:
            raise CorporateActionError("duplicate review_id in reviewed overrides")
        if identity in identities:
            raise CorporateActionError("duplicate override identity")
        matches = action_matches.get(identity, [])
        if len(matches) > 1:
            raise CorporateActionError("reviewed override matches multiple actions")
        if not matches:
            raise CorporateActionError(
                "reviewed override does not match exactly one action"
            )
        review_ids.add(review_id)
        identities.add(identity)
        validated.append((identity, review_id, factor, provenance, matches[0]))

    factors_by_identity = {}
    for identity, review_id, factor, provenance, action_index in sorted(
        validated, key=lambda row: (*row[0], row[1])
    ):
        del review_id, provenance, action_index
        factors_by_identity[identity] = factor
    return _AppliedReviewedFactorOverrides(factors_by_identity=factors_by_identity)


def adjust_ohlcv(
    frame: pd.DataFrame,
    actions: Iterable[dict[str, Any]],
    *,
    reviewed_factor_overrides: ReviewedFactorOverrides | None = None,
) -> pd.DataFrame:
    """Backward-adjust OHLCV using visible actions, preserving the input frame."""
    adjusted = frame.copy(deep=True).sort_index()
    if adjusted.empty:
        return adjusted
    missing = set(PRICE_COLUMNS + ["Volume"]) - set(adjusted.columns)
    if missing:
        raise CorporateActionError(f"OHLCV frame missing columns: {sorted(missing)}")

    action_rows = list(actions)
    applied = apply_reviewed_factor_overrides(action_rows, reviewed_factor_overrides)
    ordered = sorted(action_rows, key=lambda action: (str(action["ex_date"]), str(action.get("action_type", ""))))
    for action in ordered:
        ex_date = _frame_timestamp(action["ex_date"], adjusted.index)
        if ex_date <= adjusted.index.min() or ex_date > adjusted.index.max():
            continue
        identity = None
        if (
            applied.factors_by_identity
            and str(action.get("action_type", "")).upper() in _NON_AUTOMATIC_ACTIONS
        ):
            identity = _action_identity(action)
        factor, adjusts_volume = _action_factor(
            action,
            adjusted,
            applied.factors_by_identity.get(identity),
        )
        prior = adjusted.index < ex_date
        adjusted.loc[prior, PRICE_COLUMNS] = adjusted.loc[prior, PRICE_COLUMNS] * factor
        if adjusts_volume:
            adjusted.loc[prior, "Volume"] = adjusted.loc[prior, "Volume"] / factor
    return adjusted
