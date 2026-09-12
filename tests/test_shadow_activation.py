import copy
import pickle
from datetime import datetime, timedelta, timezone

import pytest

from src.reliability import activation
from src.reliability.activation import assess_shadow_readiness, queue_shadow_briefing
from src.reliability.corporate_action_reviews import (
    CorporateActionReviewError,
    VerifiedCorporateActionAudit,
    verified_corporate_action_audit_sha256,
)
from src.reliability.ledger import SignalLedger
from src.reliability.outbox import DeliveryOutbox
from src.reliability.shadow import ShadowCoordinator
from src.reliability.store import ReliabilityStore
from tests.corporate_action_test_support import issue_reviewed_factor_chain


NOW = datetime(2024, 7, 2, 4, 0, tzinfo=timezone.utc)


def _ready_stack(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    manifest = store.register_manifest("nse-bundle", b"bundle", "2024-07-01T18:00:00Z")
    store.put_membership("TCS", "2024-01-01", "2024-01-02T03:00:00Z", manifest)
    store.put_bar("TCS", "2024-07-01", 100, 102, 99, 101, 1000,
                  "2024-07-01T18:00:00Z", manifest)
    store.put_halal_classification(
        "TCS", "2024-06-30", "GREEN", True, "aaoifi-v1",
        "2024-06-30T12:00:00Z", manifest,
    )
    ledger = SignalLedger(store.connection)
    outbox = DeliveryOutbox(store.connection)
    return store, manifest, ledger, outbox


def _issued_audit(tmp_path):
    return issue_reviewed_factor_chain(tmp_path).audit_capability


def _mutate_reviewed_audit(chain):
    chain.reviewed_path.write_bytes(b"{}")


def _mutate_decision_csv(chain):
    (chain.packet_dir / "factor-reviews.csv").write_bytes(b"tampered decision CSV\n")


def _mutate_reviewer_policy(chain):
    chain.policy_path.write_bytes(b"{}")


def _mutate_governance_evidence(chain):
    (chain.packet_dir / "governance" / "reviewer-attestation.pdf").write_bytes(
        b"tampered governance evidence\n"
    )


def _mutate_baseline_report(chain):
    chain.baseline_path.write_bytes(b"{}")


def test_empty_database_blocks_shadow_activation(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    result = assess_shadow_readiness(
        store, SignalLedger(store.connection), DeliveryOutbox(store.connection), as_of=NOW
    )

    assert result["ready"] is False
    assert "UNIVERSE_EMPTY" in result["blockers"]


def test_complete_fresh_database_requires_verified_corporate_action_audit(tmp_path):
    store, _manifest, ledger, outbox = _ready_stack(tmp_path)

    result = assess_shadow_readiness(store, ledger, outbox, as_of=NOW)

    assert result["ready"] is False
    assert result["blockers"] == ["CORPORATE_ACTION_REVIEW"]
    assert "corporate_action_audit_sha256" not in result["metrics"]


def test_issued_corporate_action_audit_allows_shadow_activation(tmp_path):
    store, _manifest, ledger, outbox = _ready_stack(tmp_path)
    audit = _issued_audit(tmp_path)

    result = assess_shadow_readiness(
        store, ledger, outbox, as_of=NOW, corporate_action_audit=audit,
    )

    assert result["ready"] is True
    assert result["metrics"]["universe_size"] == 1
    assert result["metrics"]["bar_coverage"] == 1.0
    assert result["metrics"]["halal_coverage"] == 1.0
    assert result["metrics"]["corporate_action_audit_sha256"] == audit.audit_sha256
    assert set(result["metrics"]).isdisjoint({
        "corporate_action_audit", "artifact_binding", "reviewer_id", "authority",
    })


@pytest.mark.parametrize("factory", [
    lambda _audit: object(),
    lambda _audit: object.__new__(VerifiedCorporateActionAudit),
    lambda _audit: type(
        "LookalikeAudit", (), {"audit_sha256": "a" * 64, "complete": True},
    )(),
    lambda _audit: object.__new__(type("SubclassAudit", (VerifiedCorporateActionAudit,), {})),
])
def test_forged_corporate_action_audits_block_readiness(tmp_path, factory):
    store, _manifest, ledger, outbox = _ready_stack(tmp_path)

    result = assess_shadow_readiness(
        store, ledger, outbox, as_of=NOW,
        corporate_action_audit=factory(_issued_audit(tmp_path)),
    )

    assert result["ready"] is False
    assert "CORPORATE_ACTION_REVIEW" in result["blockers"]
    assert "corporate_action_audit_sha256" not in result["metrics"]


def test_copied_deserialized_or_mutated_audits_cannot_authorize_readiness(tmp_path):
    store, _manifest, ledger, outbox = _ready_stack(tmp_path)
    audit = _issued_audit(tmp_path)

    with pytest.raises(CorporateActionReviewError):
        copy.copy(audit)
    with pytest.raises(CorporateActionReviewError):
        pickle.loads(pickle.dumps(audit))

    object.__setattr__(audit, "_audit_sha256", "forged")
    result = assess_shadow_readiness(
        store, ledger, outbox, as_of=NOW, corporate_action_audit=audit,
    )

    assert result["ready"] is False
    assert "CORPORATE_ACTION_REVIEW" in result["blockers"]


@pytest.mark.parametrize(("source", "policy_version", "mutate"), [
    ("reviewed-audit", "corporate-action-review-policy-v1", _mutate_reviewed_audit),
    ("decision-csv", "corporate-action-review-policy-v1", _mutate_decision_csv),
    ("reviewer-policy", "corporate-action-review-policy-v1", _mutate_reviewer_policy),
    ("governance-evidence", "corporate-action-review-policy-v2", _mutate_governance_evidence),
    ("baseline-report", "corporate-action-review-policy-v1", _mutate_baseline_report),
])
def test_stale_audit_sources_block_readiness_and_queue_without_side_effects(
    tmp_path,
    source,
    policy_version,
    mutate,
):
    store, manifest, ledger, outbox = _ready_stack(tmp_path)
    chain = issue_reviewed_factor_chain(
        tmp_path,
        name=source,
        reviewer_policy_version=policy_version,
    )
    mutate(chain)

    readiness = assess_shadow_readiness(
        store,
        ledger,
        outbox,
        as_of=NOW,
        corporate_action_audit=chain.audit_capability,
    )
    queued = queue_shadow_briefing(
        cards=[{"ticker": "TCS", "entry": 101, "stop": 98, "target": 107}],
        message="BUY TCS",
        store=store,
        coordinator=ShadowCoordinator(ledger, outbox),
        as_of=NOW,
        strategy_version="rule-v2.0.0",
        data_manifest_hash=manifest,
        corporate_action_audit=chain.audit_capability,
    )

    assert verified_corporate_action_audit_sha256(chain.audit_capability) is None
    assert readiness["ready"] is False
    assert "CORPORATE_ACTION_REVIEW" in readiness["blockers"]
    assert queued["queued"] is False
    assert "CORPORATE_ACTION_REVIEW" in queued["blockers"]
    assert ledger.events() == []
    assert outbox.metrics()["total"] == 0


def test_activation_uses_atomic_audit_accessor_not_capability_properties(tmp_path, monkeypatch):
    store, _manifest, ledger, outbox = _ready_stack(tmp_path)
    chain = issue_reviewed_factor_chain(tmp_path)
    expected_sha256 = chain.reviewed_sha256

    monkeypatch.setattr(
        VerifiedCorporateActionAudit,
        "audit_sha256",
        property(lambda _self: (_ for _ in ()).throw(CorporateActionReviewError("forged"))),
    )

    result = assess_shadow_readiness(
        store,
        ledger,
        outbox,
        as_of=NOW,
        corporate_action_audit=chain.audit_capability,
    )

    assert result["ready"] is True
    assert result["metrics"]["corporate_action_audit_sha256"] == expected_sha256


def test_atomic_audit_accessor_prevents_check_then_use_metric_injection(
    tmp_path,
    monkeypatch,
):
    store, _manifest, ledger, outbox = _ready_stack(tmp_path)
    chain = issue_reviewed_factor_chain(tmp_path)
    consume = activation.verified_corporate_action_audit_sha256

    def consume_then_mutate(value):
        trusted_sha256 = consume(value)
        object.__setattr__(value, "_audit_sha256", "injected-after-consumption")
        return trusted_sha256

    monkeypatch.setattr(
        activation,
        "verified_corporate_action_audit_sha256",
        consume_then_mutate,
    )
    result = assess_shadow_readiness(
        store,
        ledger,
        outbox,
        as_of=NOW,
        corporate_action_audit=chain.audit_capability,
    )

    assert result["ready"] is True
    assert result["metrics"]["corporate_action_audit_sha256"] == chain.reviewed_sha256
    assert result["metrics"]["corporate_action_audit_sha256"] != "injected-after-consumption"

    result_after_mutation = assess_shadow_readiness(
        store,
        ledger,
        outbox,
        as_of=NOW,
        corporate_action_audit=chain.audit_capability,
    )
    assert result_after_mutation["ready"] is False
    assert "CORPORATE_ACTION_REVIEW" in result_after_mutation["blockers"]


def test_stale_prices_block_shadow_activation(tmp_path):
    store, _manifest, ledger, outbox = _ready_stack(tmp_path)

    result = assess_shadow_readiness(
        store, ledger, outbox, as_of=NOW + timedelta(days=10), max_bar_age_days=5,
        corporate_action_audit=_issued_audit(tmp_path),
    )

    assert result["ready"] is False
    assert "BAR_FRESHNESS" in result["blockers"]


def test_ready_shadow_briefing_is_persisted_and_queued(tmp_path):
    store, manifest, ledger, outbox = _ready_stack(tmp_path)
    coordinator = ShadowCoordinator(ledger, outbox)

    result = queue_shadow_briefing(
        cards=[{"ticker": "TCS", "entry": 101, "stop": 98, "target": 107}],
        message="BUY TCS",
        store=store,
        coordinator=coordinator,
        as_of=NOW,
        strategy_version="rule-v2.0.0",
        data_manifest_hash=manifest,
        corporate_action_audit=_issued_audit(tmp_path),
    )

    assert result["queued"] is True
    assert outbox.metrics()["total"] == 1
    assert ledger.verify_chain()["valid"] is True


def test_unready_shadow_briefing_is_not_queued(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    ledger = SignalLedger(store.connection)
    outbox = DeliveryOutbox(store.connection)

    result = queue_shadow_briefing(
        cards=[], message="NO SIGNAL", store=store,
        coordinator=ShadowCoordinator(ledger, outbox), as_of=NOW,
        strategy_version="rule-v2.0.0", data_manifest_hash="a" * 64,
    )

    assert result["queued"] is False
    assert "UNIVERSE_EMPTY" in result["blockers"]
    assert outbox.metrics()["total"] == 0


def test_blocked_audit_queue_has_no_snapshot_outbox_ledger_or_delivery_side_effects(tmp_path):
    store, manifest, ledger, outbox = _ready_stack(tmp_path)
    coordinator = ShadowCoordinator(ledger, outbox)
    deliveries = []

    result = queue_shadow_briefing(
        cards=[{"ticker": "TCS", "entry": 101, "stop": 98, "target": 107}],
        message="BUY TCS",
        store=store,
        coordinator=coordinator,
        as_of=NOW,
        strategy_version="rule-v2.0.0",
        data_manifest_hash=manifest,
    )

    assert result["queued"] is False
    assert "CORPORATE_ACTION_REVIEW" in result["blockers"]
    assert ledger.events() == []
    assert outbox.metrics()["total"] == 0
    assert coordinator.deliver_due(lambda message: deliveries.append(message), now=NOW)["delivered"] == 0
    assert deliveries == []


def test_known_non_tradeable_member_does_not_block_database_readiness(tmp_path):
    store, manifest, ledger, outbox = _ready_stack(tmp_path)
    store.put_membership("BANK", "2024-01-01", "2024-01-02T03:00:00Z", manifest)
    store.put_bar("BANK", "2024-07-01", 10, 11, 9, 10, 1000,
                  "2024-07-01T18:00:00Z", manifest)
    store.put_halal_classification(
        "BANK", "2024-06-30", "RED", False, "aaoifi-v1",
        "2024-06-30T12:00:00Z", manifest, reason="riba-financial",
    )

    result = assess_shadow_readiness(
        store, ledger, outbox, as_of=NOW,
        corporate_action_audit=_issued_audit(tmp_path),
    )

    assert result["ready"] is True
    assert result["metrics"]["non_tradeable"] == ["BANK"]


def test_non_tradeable_signal_is_rejected_even_when_database_is_ready(tmp_path):
    store, manifest, ledger, outbox = _ready_stack(tmp_path)
    store.put_membership("BANK", "2024-01-01", "2024-01-02T03:00:00Z", manifest)
    store.put_bar("BANK", "2024-07-01", 10, 11, 9, 10, 1000,
                  "2024-07-01T18:00:00Z", manifest)
    store.put_halal_classification(
        "BANK", "2024-06-30", "RED", False, "aaoifi-v1",
        "2024-06-30T12:00:00Z", manifest,
    )

    result = queue_shadow_briefing(
        cards=[{"ticker": "BANK"}], message="BUY BANK", store=store,
        coordinator=ShadowCoordinator(ledger, outbox), as_of=NOW,
        strategy_version="rule-v2.0.0", data_manifest_hash=manifest,
        corporate_action_audit=_issued_audit(tmp_path),
    )

    assert result["queued"] is False
    assert "SIGNAL_HALAL_BLOCKED" in result["blockers"]
