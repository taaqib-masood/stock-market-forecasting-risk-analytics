"""Automated, hash-bound release compliance audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from src.reliability.corporate_action_reviews import VerifiedCorporateActionAudit
from src.reliability.governance import evaluate_release, load_policy


def audit_release_evidence(
    evidence_path: str | Path,
    policy_path: str | Path,
    *,
    corporate_action_audit: VerifiedCorporateActionAudit | None = None,
) -> dict:
    evidence_path = Path(evidence_path)
    policy_path = Path(policy_path)
    evidence_bytes = evidence_path.read_bytes()
    policy_bytes = policy_path.read_bytes()
    evidence = json.loads(evidence_bytes)
    verdict = evaluate_release(
        evidence,
        load_policy(policy_path),
        corporate_action_audit=corporate_action_audit,
    )
    return {
        **verdict,
        "as_of": str(evidence.get("as_of", "")),
        "strategy_version": evidence.get("strategy_version"),
        "evidence_path": str(evidence_path),
        "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        "policy_path": str(policy_path),
        "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Boro release evidence")
    parser.add_argument("evidence")
    parser.add_argument("--policy", default="config/reliability-policy.json")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit_release_evidence(
        args.evidence,
        args.policy,
        corporate_action_audit=None,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not result["approved"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
