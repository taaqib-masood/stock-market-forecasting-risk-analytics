"""Audit retained corporate-action coverage and point-in-time provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from src.reliability.nse_normalizers import (
    normalize_corporate_actions_snapshot_bytes,
    reconcile_corporate_action_announcements_bytes,
)
from src.reliability.corporate_action_reviews import (
    BASE_FIELDS,
    CorporateActionReviewError,
    build_review_rows,
    validate_review_packet,
)
from src.reliability.preregistration import canonical_json_bytes


PRICE_ACTIONS = {"BONUS", "SPLIT", "DIVIDEND", "RIGHTS", "MERGER", "DEMERGER"}
AUTOMATIC_ACTIONS = {"BONUS", "SPLIT", "DIVIDEND"}


def _date(value: str) -> date:
    for pattern in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            pass
    raise ValueError(f"invalid date: {value}")


def _months(start: date, end: date) -> list[str]:
    output = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        output.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return output


def _source_bytes(record: dict, catalogue_path: Path) -> tuple[Path, bytes | None, str | None]:
    path = Path(str(record.get("path", "")))
    if not path.is_absolute() and not path.exists():
        path = catalogue_path.parent / path
    if not path.is_file():
        return path, None, "MISSING_FILE"
    try:
        content = path.read_bytes()
    except OSError:
        return path, None, "MISSING_FILE"
    if not record.get("sha256") or hashlib.sha256(content).hexdigest() != record["sha256"]:
        return path, None, "SHA256_MISMATCH"
    return path, content, None


def _consume_accepted_reviews(
    accepted: dict,
    expected_rows: list[dict],
    *,
    accepted_decision: str,
) -> dict[str, dict]:
    """Require each accepted decision to match one current immutable queue row."""
    if not isinstance(accepted, dict):
        raise CorporateActionReviewError("accepted reviews must be keyed by review ID")
    expected_by_id = {row["review_id"]: row for row in expected_rows}
    if len(expected_by_id) != len(expected_rows):
        raise CorporateActionReviewError("current review queue contains duplicate review IDs")

    consumed = {}
    for review_id, decision in accepted.items():
        expected = expected_by_id.get(review_id)
        if (
            expected is None
            or not isinstance(decision, dict)
            or decision.get("review_id") != review_id
            or decision.get("decision") != accepted_decision
            or any(decision.get(field) != expected[field] for field in BASE_FIELDS)
            or review_id in consumed
        ):
            raise CorporateActionReviewError("accepted review is unused or conflicts with current queue")
        consumed[review_id] = decision
    return consumed


def _consume_validated_decisions(
    decisions: dict,
    expected_rows: list[dict],
    *,
    allowed_decisions: set[str],
) -> dict[str, dict]:
    """Require the verifier snapshot to cover the current queue exactly once."""
    if not isinstance(decisions, dict):
        raise CorporateActionReviewError("validated review decisions must be keyed by review ID")
    expected_by_id = {row["review_id"]: row for row in expected_rows}
    if len(expected_by_id) != len(expected_rows) or set(decisions) != set(expected_by_id):
        raise CorporateActionReviewError("validated decisions do not match current queue")

    consumed = {}
    for review_id, decision in decisions.items():
        expected = expected_by_id[review_id]
        if (
            not isinstance(decision, dict)
            or decision.get("review_id") != review_id
            or decision.get("decision") not in allowed_decisions
            or any(decision.get(field) != expected[field] for field in BASE_FIELDS)
            or review_id in consumed
        ):
            raise CorporateActionReviewError("validated decision conflicts with current queue")
        consumed[review_id] = decision
    return consumed


def audit_corporate_actions(
    catalogue_path: str | Path,
    *,
    start: str,
    end: str,
    review_packet_dir: str | Path | None = None,
    reviewer_policy_path: str | Path | None = None,
    baseline_report_path: str | Path | None = None,
) -> dict:
    review_inputs = (
        review_packet_dir,
        reviewer_policy_path,
        baseline_report_path,
    )
    if any(value is None for value in review_inputs) and any(
        value is not None for value in review_inputs
    ):
        raise ValueError(
            "review packet, reviewer policy, and baseline report must be supplied together"
        )
    catalogue_path = Path(catalogue_path)
    start_date, end_date = _date(start), _date(end)
    expected_months = set(_months(start_date, end_date))
    covered_months: set[str] = set()
    invalid_sources: list[dict[str, str]] = []
    normalized: list[dict] = []

    latest: dict[tuple[str, str | None, str | None], tuple[int, dict]] = {}
    for number, line in enumerate(catalogue_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("status") not in {"downloaded", "cached"}:
            continue
        if record.get("kind") not in {"corporate_actions", "corporate_announcements"}:
            continue
        params = record.get("params") or {}
        key = (record["kind"], params.get("from_date"), params.get("to_date"))
        latest[key] = (number, record)

    records = []
    for number, record in latest.values():
        path, content, reason = _source_bytes(record, catalogue_path)
        if reason:
            invalid_sources.append({"line": number, "reason": reason})
            continue
        records.append((record, path, content))

    announcements = []
    for record, path, content in records:
        if record["kind"] != "corporate_announcements":
            continue
        params = record.get("params") or {}
        announcements.append((_date(params["from_date"]), _date(params["to_date"]), content))
    for record, path, content in records:
        if record["kind"] != "corporate_actions":
            continue
        params = record.get("params") or {}
        range_start = _date(params["from_date"])
        range_end = _date(params["to_date"])
        covered_months.update(_months(max(start_date, range_start), min(end_date, range_end)))
        candidate_paths = [
            candidate_content for announcement_start, announcement_end, candidate_content in announcements
            if announcement_end >= range_start - timedelta(days=180)
            and announcement_start <= range_end
        ]
        if candidate_paths:
            rows = reconcile_corporate_action_announcements_bytes(
                content, candidate_paths, available_at=record["available_at"]
            )
        else:
            rows = normalize_corporate_actions_snapshot_bytes(
                content,
                available_at=record["available_at"],
            )
        normalized.extend(
            row for row in rows if start_date <= _date(row["ex_date"]) <= end_date
        )

    price_actions = [row for row in normalized if row["action_type"] in PRICE_ACTIONS]
    point_in_time = [
        row for row in price_actions
        if row["payload"].get("availability_source") in {
            "exchange_broadcast", "matched_announcement"
        }
    ]
    point_in_time_sources = {"exchange_broadcast", "matched_announcement"}
    visibility_review_queue = sorted(({
        "symbol": row["symbol"],
        "action_type": row["action_type"],
        "ex_date": row["ex_date"],
        "purpose": row["payload"].get("purpose", ""),
        "reason": row["payload"].get("availability_source", "missing_availability"),
    } for row in price_actions
        if row["payload"].get("availability_source") not in point_in_time_sources),
        key=lambda row: (row["ex_date"], row["symbol"], row["action_type"]),
    )
    retrieval_only = len(price_actions) - len(point_in_time)
    unquantifiable = [
        row for row in price_actions
        if row["action_type"] not in AUTOMATIC_ACTIONS
    ]
    factor_review_queue = sorted(({
        "symbol": row["symbol"],
        "action_type": row["action_type"],
        "ex_date": row["ex_date"],
        "purpose": row["payload"].get("purpose", ""),
        "reason": "reviewed adjustment factor required",
    } for row in unquantifiable),
        key=lambda row: (row["ex_date"], row["symbol"], row["action_type"]),
    )
    visibility_rows = build_review_rows("visibility", visibility_review_queue)
    factor_rows = build_review_rows("factor", factor_review_queue)
    accepted_visibility: dict[str, dict] = {}
    accepted_factors: dict[str, dict] = {}
    visibility_decisions: dict[str, dict] = {}
    factor_decisions: dict[str, dict] = {}
    review_artifact_binding: dict[str, str] | None = None
    review_counts = {
        "visibility": {"accepted": 0, "pending": 0, "rejected": 0},
        "factor": {"accepted": 0, "pending": 0, "rejected": 0},
    }
    if review_packet_dir is not None:
        validation = validate_review_packet(
            review_packet_dir,
            visibility_queue=visibility_review_queue,
            factor_queue=factor_review_queue,
            policy_path=reviewer_policy_path,
            baseline_report_path=baseline_report_path,
        )
        if not isinstance(validation, dict):
            raise CorporateActionReviewError("review validation result is invalid")
        visibility_decisions = _consume_validated_decisions(
            validation.get("visibility_decisions"),
            visibility_rows,
            allowed_decisions={"PENDING", "CONFIRMED", "REJECTED"},
        )
        factor_decisions = _consume_validated_decisions(
            validation.get("factor_decisions"),
            factor_rows,
            allowed_decisions={"PENDING", "APPROVED", "REJECTED"},
        )
        accepted_visibility = _consume_accepted_reviews(
            validation.get("accepted_visibility"),
            visibility_rows,
            accepted_decision="CONFIRMED",
        )
        accepted_factors = _consume_accepted_reviews(
            validation.get("accepted_factors"),
            factor_rows,
            accepted_decision="APPROVED",
        )
        if set(accepted_visibility) & set(accepted_factors):
            raise CorporateActionReviewError("review IDs conflict across review queues")
        counts = validation.get("counts")
        if not isinstance(counts, dict):
            raise CorporateActionReviewError("review validation counts are invalid")
        for queue_kind in ("visibility", "factor"):
            queue_counts = counts.get(queue_kind)
            if (
                not isinstance(queue_counts, dict)
                or set(queue_counts) != {"accepted", "pending", "rejected"}
                or any(not isinstance(value, int) or value < 0 for value in queue_counts.values())
            ):
                raise CorporateActionReviewError("review validation counts are invalid")
            review_counts[queue_kind] = queue_counts.copy()
        if review_counts["visibility"]["accepted"] != len(accepted_visibility):
            raise CorporateActionReviewError("visibility accepted-review count conflicts")
        if review_counts["factor"]["accepted"] != len(accepted_factors):
            raise CorporateActionReviewError("factor accepted-review count conflicts")
        if set(accepted_visibility) != {
            review_id for review_id, row in visibility_decisions.items()
            if row["decision"] == "CONFIRMED"
        }:
            raise CorporateActionReviewError("visibility accepted reviews conflict with snapshot")
        if set(accepted_factors) != {
            review_id for review_id, row in factor_decisions.items()
            if row["decision"] == "APPROVED"
        }:
            raise CorporateActionReviewError("factor accepted reviews conflict with snapshot")
        if review_counts["visibility"] != {
            "accepted": len(accepted_visibility),
            "pending": sum(
                row["decision"] == "PENDING" for row in visibility_decisions.values()
            ),
            "rejected": sum(
                row["decision"] == "REJECTED" for row in visibility_decisions.values()
            ),
        }:
            raise CorporateActionReviewError("visibility review counts conflict with snapshot")
        if review_counts["factor"] != {
            "accepted": len(accepted_factors),
            "pending": sum(
                row["decision"] == "PENDING" for row in factor_decisions.values()
            ),
            "rejected": sum(
                row["decision"] == "REJECTED" for row in factor_decisions.values()
            ),
        }:
            raise CorporateActionReviewError("factor review counts conflict with snapshot")
        review_artifact_binding = validation.get("review_artifact_binding")
        if not isinstance(review_artifact_binding, dict):
            raise CorporateActionReviewError(
                "review validation artifact binding is invalid"
            )
        review_artifact_binding = review_artifact_binding.copy()

    accepted_visibility_ids = set(accepted_visibility)
    accepted_factor_ids = set(accepted_factors)
    unresolved_visibility = []
    for queue, row in zip(visibility_review_queue, visibility_rows):
        if row["review_id"] in accepted_visibility_ids:
            continue
        unresolved = queue.copy()
        if review_packet_dir is not None:
            unresolved["decision"] = visibility_decisions[row["review_id"]]["decision"]
        unresolved_visibility.append(unresolved)
    unresolved_factors = []
    for queue, row in zip(factor_review_queue, factor_rows):
        if row["review_id"] in accepted_factor_ids:
            continue
        unresolved = queue.copy()
        if review_packet_dir is not None:
            unresolved["decision"] = factor_decisions[row["review_id"]]["decision"]
        unresolved_factors.append(unresolved)
    reviewed_factor_overrides = sorted(({
        "review_id": review_id,
        "symbol": decision["symbol"],
        "action_type": decision["action_type"],
        "ex_date": decision["ex_date"],
        "purpose": decision["purpose"],
        "adjustment_factor": float(decision["adjustment_factor"]),
        "method": decision["method"],
        "evidence_path": decision["evidence_path"],
        "evidence_sha256": decision["evidence_sha256"],
        "evidence_source_url": decision["evidence_source_url"],
        "confirmed_available_at": decision["confirmed_available_at"],
        "reviewer_id": decision["reviewer_id"],
        "reviewed_at": decision["reviewed_at"],
    } for review_id, decision in accepted_factors.items()), key=lambda row: (
        row["ex_date"], row["symbol"], row["action_type"], row["purpose"], row["review_id"],
    ))
    effective_point_in_time = len(point_in_time) + len(accepted_visibility)
    effective_retrieval_only = retrieval_only - len(accepted_visibility)
    effective_unquantifiable = len(unquantifiable) - len(accepted_factors)
    missing_months = sorted(expected_months - covered_months)
    blockers = []
    if missing_months:
        blockers.append("MISSING_MONTHS")
    if effective_retrieval_only:
        blockers.append("NON_POINT_IN_TIME_ACTIONS")
    if effective_unquantifiable:
        blockers.append("UNQUANTIFIABLE_ACTIONS")
    if invalid_sources:
        blockers.append("SOURCE_INTEGRITY")
    result = {
        "complete": not blockers,
        "status": "VERIFIED" if not blockers else "REVIEW_REQUIRED",
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "counts": {
            "expected_months": len(expected_months),
            "covered_months": len(expected_months & covered_months),
            "normalized_actions": len(normalized),
            "price_actions": len(price_actions),
            "point_in_time_price_actions": effective_point_in_time,
            "retrieval_only_price_actions": effective_retrieval_only,
            "unquantifiable_price_actions": effective_unquantifiable,
            "automatic_visibility_actions": len(point_in_time),
            "reviewed_visibility_actions": len(accepted_visibility),
            "pending_visibility_actions": review_counts["visibility"]["pending"],
            "rejected_visibility_actions": review_counts["visibility"]["rejected"],
            "automatic_factor_actions": len(price_actions) - len(unquantifiable),
            "reviewed_factor_actions": len(accepted_factors),
            "pending_factor_actions": review_counts["factor"]["pending"],
            "rejected_factor_actions": review_counts["factor"]["rejected"],
        },
        "missing_months": missing_months,
        "invalid_sources": invalid_sources,
        "visibility_review_queue": unresolved_visibility,
        "factor_review_queue": unresolved_factors,
        "reviewed_factor_overrides": reviewed_factor_overrides,
        "blockers": blockers,
    }
    if review_artifact_binding is not None:
        result["review_artifact_binding"] = review_artifact_binding
        result["review_decision_snapshot"] = {
            "visibility": [
                visibility_decisions[review_id]
                for review_id in sorted(visibility_decisions)
            ],
            "factor": [
                factor_decisions[review_id]
                for review_id in sorted(factor_decisions)
            ],
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit corporate-action source evidence")
    parser.add_argument("catalogue")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--review-packet-dir")
    parser.add_argument("--reviewer-policy")
    parser.add_argument("--baseline-review-report")
    parser.add_argument("--output")
    args = parser.parse_args()
    review_inputs = (
        args.review_packet_dir,
        args.reviewer_policy,
        args.baseline_review_report,
    )
    if any(value is None for value in review_inputs) and any(
        value is not None for value in review_inputs
    ):
        parser.error(
            "--review-packet-dir, --reviewer-policy, and --baseline-review-report "
            "must be supplied together"
        )
    result = audit_corporate_actions(
        args.catalogue,
        start=args.start,
        end=args.end,
        review_packet_dir=args.review_packet_dir,
        reviewer_policy_path=args.reviewer_policy,
        baseline_report_path=args.baseline_review_report,
    )
    rendered = canonical_json_bytes(result).decode("utf-8")
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
