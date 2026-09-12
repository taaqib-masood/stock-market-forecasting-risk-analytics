import copy
import csv
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.reliability.corporate_action_audit import audit_corporate_actions
from src.reliability.corporate_action_review_packet import export_review_packet
from src.reliability.corporate_action_reviews import (
    ReviewedFactorOverrides,
    VerifiedCorporateActionAudit,
    load_reviewed_factor_overrides,
    load_verified_corporate_action_audit,
)
from src.reliability.preregistration import canonical_json_bytes


EVIDENCE_PATH = "evidence/nse-notice.txt"
EVIDENCE_SOURCE_URL = (
    "https://www.nseindia.com/corporates/corporateActions"
)
METHOD = "Rights theoretical ex-price formula using notice terms."
REVIEWER_ID = "independent-reviewer"
CONFIRMED_AVAILABLE_AT = "2024-01-02T10:00:00Z"
REVIEWED_AT = "2024-01-02T12:00:00Z"


@dataclass(frozen=True)
class IssuedFactorChain:
    capability: ReviewedFactorOverrides
    audit_capability: VerifiedCorporateActionAudit
    actions: tuple[dict, ...]
    reviewed_report: dict
    reviewed_path: Path
    reviewed_sha256: str
    baseline_path: Path
    packet_dir: Path
    policy_path: Path


def rights_action(
    *,
    symbol: str = "TCS",
    purpose: str = "Rights 1:4 @ Premium Rs 10",
    ex_date: str = "2024-01-03",
) -> dict:
    return {
        "symbol": symbol,
        "action_type": "RIGHTS",
        "ex_date": ex_date,
        "payload": {
            "purpose": purpose,
            "source": {
                "kind": "nse_corporate_actions",
                "symbol": symbol,
            },
        },
        "exchange_fields": {
            "series": "EQ",
            "record_date": ex_date,
        },
    }


def issue_reviewed_factor_chain(
    tmp_path: Path,
    *,
    actions: list[dict] | tuple[dict, ...] | None = None,
    factors: list[str] | tuple[str, ...] | None = None,
    name: str = "review-chain",
    reviewer_policy_version: str = "corporate-action-review-policy-v1",
    after_factor_loader: Callable[[Path], None] | None = None,
) -> IssuedFactorChain:
    action_rows = copy.deepcopy(
        list(actions) if actions is not None else [rights_action()]
    )
    factor_values = list(factors) if factors is not None else ["0.75"]
    if len(action_rows) != len(factor_values):
        raise ValueError("one factor is required for each review action")
    if any(row.get("action_type") != "RIGHTS" for row in action_rows):
        raise ValueError("this test fixture currently supports RIGHTS actions")

    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=False)
    snapshot = root / "actions.json"
    snapshot_rows = []
    for action in action_rows:
        ex_date = date.fromisoformat(action["ex_date"])
        snapshot_rows.append({
            "symbol": action["symbol"],
            "series": action["exchange_fields"]["series"],
            "subject": action["payload"]["purpose"],
            "exDate": ex_date.strftime("%d-%b-%Y"),
            "recDate": ex_date.strftime("%d-%b-%Y"),
            "caBroadcastDate": "01-Jan-2024 10:00:00",
        })
    snapshot.write_text(json.dumps(snapshot_rows), encoding="utf-8")

    catalogue = root / "source-catalogue.jsonl"
    catalogue.write_text(
        json.dumps({
            "kind": "corporate_actions",
            "status": "downloaded",
            "path": str(snapshot),
            "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            "available_at": "2024-01-02T00:00:00Z",
            "params": {
                "from_date": "01-01-2024",
                "to_date": "31-01-2024",
            },
        }) + "\n",
        encoding="utf-8",
    )

    baseline = audit_corporate_actions(
        catalogue,
        start="2024-01-01",
        end="2024-01-31",
    )
    baseline_path = root / "baseline-audit.json"
    baseline_path.write_bytes(canonical_json_bytes(baseline))
    packet_dir = root / "packet"
    exported = export_review_packet(
        baseline_path,
        packet_dir,
        reviewer_policy_version=reviewer_policy_version,
    )

    evidence_dir = packet_dir / "evidence"
    evidence_dir.mkdir()
    evidence = evidence_dir / "nse-notice.txt"
    evidence.write_bytes(b"NSE primary corporate action notice\n")
    evidence_sha256 = hashlib.sha256(evidence.read_bytes()).hexdigest()

    factor_csv = exported["factor_csv"]
    with factor_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    if len(rows) != len(factor_values):
        raise AssertionError("audit factor queue does not match fixture actions")
    for row, factor in zip(rows, factor_values, strict=True):
        row.update({
            "decision": "APPROVED",
            "evidence_path": EVIDENCE_PATH,
            "evidence_sha256": evidence_sha256,
            "evidence_source_url": EVIDENCE_SOURCE_URL,
            "reviewer_id": REVIEWER_ID,
            "reviewed_at": REVIEWED_AT,
            "confirmed_available_at": CONFIRMED_AVAILABLE_AT,
            "adjustment_factor": factor,
            "method": METHOD,
            "notes": "Primary exchange notice retained.",
        })
    with factor_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    policy_path = root / "reviewer-policy.json"
    policy = {
            "policy_version": "corporate-action-review-policy-v1",
            "authorized_reviewers": [REVIEWER_ID],
            "prohibited_reviewers": ["issuer-employee"],
            "allowed_evidence_hosts": ["www.nseindia.com"],
    }
    if reviewer_policy_version == "corporate-action-review-policy-v2":
        governance_dir = packet_dir / "governance"
        governance_dir.mkdir()
        attestation = governance_dir / "reviewer-attestation.pdf"
        approval = governance_dir / "owner-approval.pdf"
        attestation.write_bytes(b"Independent reviewer attestation\n")
        approval.write_bytes(b"Governance owner approval\n")
        policy = {
            "policy_version": reviewer_policy_version,
            "authorized_reviewers": [{
                "reviewer_id": REVIEWER_ID,
                "actor_type": "HUMAN",
                "scopes": ["visibility", "factor"],
                "valid_from": "2024-01-01T00:00:00Z",
                "valid_through": "2024-12-31T00:00:00Z",
                "revoked": False,
                "independence_evidence_path": "governance/reviewer-attestation.pdf",
                "independence_evidence_sha256": hashlib.sha256(
                    attestation.read_bytes()
                ).hexdigest(),
                "governance_owner_id": "owner-001",
                "approved_at": "2024-01-01T00:00:00Z",
                "approval_evidence_path": "governance/owner-approval.pdf",
                "approval_evidence_sha256": hashlib.sha256(
                    approval.read_bytes()
                ).hexdigest(),
            }],
            "prohibited_reviewers": ["codex", "taaqib-masood"],
            "prohibited_actor_types": ["AI", "SERVICE_ACCOUNT"],
            "allowed_evidence_hosts": ["www.nseindia.com"],
        }
    elif reviewer_policy_version != "corporate-action-review-policy-v1":
        raise ValueError("reviewer policy version is unsupported")
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    reviewed = audit_corporate_actions(
        catalogue,
        start="2024-01-01",
        end="2024-01-31",
        review_packet_dir=packet_dir,
        reviewer_policy_path=policy_path,
        baseline_report_path=baseline_path,
    )
    reviewed_path = root / "reviewed-audit.json"
    reviewed_path.write_bytes(canonical_json_bytes(reviewed))
    reviewed_sha256 = hashlib.sha256(reviewed_path.read_bytes()).hexdigest()
    capability = load_reviewed_factor_overrides(
        reviewed_path,
        expected_sha256=reviewed_sha256,
        packet_dir=packet_dir,
        policy_path=policy_path,
        baseline_report_path=baseline_path,
    )
    if after_factor_loader is not None:
        after_factor_loader(reviewed_path)
    audit_capability = load_verified_corporate_action_audit(
        reviewed_path,
        expected_sha256=reviewed_sha256,
        packet_dir=packet_dir,
        policy_path=policy_path,
        baseline_report_path=baseline_path,
    )
    return IssuedFactorChain(
        capability=capability,
        audit_capability=audit_capability,
        actions=tuple(copy.deepcopy(action_rows)),
        reviewed_report=copy.deepcopy(reviewed),
        reviewed_path=reviewed_path,
        reviewed_sha256=reviewed_sha256,
        baseline_path=baseline_path,
        packet_dir=packet_dir,
        policy_path=policy_path,
    )
