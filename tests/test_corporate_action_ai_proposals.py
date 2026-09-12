from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.reliability.adjusted_prices import (
    CorporateActionError,
    apply_reviewed_factor_overrides,
)
from src.reliability.corporate_action_ai_proposals import (
    AIProposalDurabilityError,
    AIProposalError,
    append_ai_proposals,
    build_ai_proposal,
)
from src.reliability.corporate_action_factor_worksheets import (
    build_factor_worksheet,
)
from src.reliability.corporate_action_reviews import build_review_rows
from src.reliability.preregistration import canonical_json_bytes


WORKFLOW_SHA256 = "f" * 64
ACTION_SHA256 = "a" * 64
SNAPSHOT_SHA256 = "b" * 64
TERMS_SHA256 = "c" * 64
PRICE_SHA256 = "d" * 64


def _review(*, queue_kind: str = "visibility") -> dict[str, str]:
    source = {
        "symbol": "ABC",
        "action_type": "RIGHTS",
        "ex_date": "2024-01-31",
        "purpose": "Rights 1:4 @ Rs 80",
        "reason": (
            "announcement visibility review required"
            if queue_kind == "visibility"
            else "reviewed adjustment factor required"
        ),
    }
    return build_review_rows(queue_kind, [source])[0]


def _candidate() -> dict[str, object]:
    return {
        "seq_id": "123",
        "symbol": "ABC",
        "broadcast_at": "2024-01-15T10:00:00+05:30",
        "description": "Rights issue",
        "subject": "Rights 1:4",
        "attachment_text": "Letter of offer",
        "attachment_url": "https://nsearchives.nseindia.com/rights.pdf",
        "snapshot_path": "data/reliability/announcements-2024-01.json",
        "snapshot_sha256": SNAPSHOT_SHA256,
        "snapshot_bytes": 1234,
        "snapshot_available_at": "2024-01-15T04:31:00Z",
        "ambiguity_reason": "CANDIDATE_NOT_CANONICAL",
    }


def _index(
    review: dict[str, str],
    *,
    with_candidate: bool = True,
) -> dict[str, object]:
    candidates = [_candidate()] if with_candidate else []
    return {
        "schema_version": "corporate-action-evidence-index-v1",
        "proposal_only": True,
        "review_id": review["review_id"],
        "queue_kind": "visibility" if "visibility" in review["reason"] else "factor",
        "review_identity": {
            field: review[field]
            for field in ("symbol", "action_type", "ex_date", "purpose", "reason")
        },
        "action_source": {
            "path": "data/reliability/actions-2024-01.json",
            "sha256": ACTION_SHA256,
            "bytes": 9876,
            "available_at": "2024-01-02T00:00:00Z",
        },
        "announcement_candidates": candidates,
        "candidate_resolution": (
            "AMBIGUOUS_REVIEW_REQUIRED"
            if candidates
            else "NO_COMPATIBLE_CANDIDATE"
        ),
    }


def _worksheet(review: dict[str, str]) -> dict[str, object]:
    return build_factor_worksheet(
        review,
        retained_inputs={
            "rights_terms": {
                "value": review["purpose"],
                "path": "data/reliability/actions-2024-01.json",
                "sha256": TERMS_SHA256,
                "available_at": "2024-01-15T10:00:00Z",
            },
            "cum_rights_price": {
                "value": "100",
                "path": "data/reliability/prices/ABC-2024-01-30.json",
                "sha256": PRICE_SHA256,
                "available_at": "2024-01-30T10:00:00Z",
            },
        },
    )


def _candidate_manifest(review: dict[str, str]) -> dict[str, object]:
    return {
        "schema_version": "corporate-action-candidate-evidence-v1",
        "proposal_only": True,
        "records": [
            {
                "schema_version": "corporate-action-candidate-evidence-v1",
                "proposal_only": True,
                "review_id": review["review_id"],
                "candidate_url": _candidate()["attachment_url"],
                "attachment_sha256": "e" * 64,
                "attachment_path": (
                    "data/reliability/corporate-action-ai-proposals/"
                    "evidence/sha256/ee/" + "e" * 64 + ".pdf"
                ),
                "byte_count": 4567,
                "attempted_at": "2024-02-01T00:00:00Z",
                "retrieved_at": "2024-02-01T00:00:01Z",
                "source_snapshot_sha256": SNAPSHOT_SHA256,
                "status": "RETAINED",
                "failure_code": None,
            }
        ],
    }


def _proposal(
    *,
    queue_kind: str = "visibility",
    generated_at: str = "2024-02-01T00:00:00Z",
    with_candidate: bool = True,
) -> dict[str, object]:
    review = _review(queue_kind=queue_kind)
    return build_ai_proposal(
        review_row=review,
        evidence_index=_index(review, with_candidate=with_candidate),
        factor_worksheet=_worksheet(review) if queue_kind == "factor" else None,
        model_id="gpt-5.6-sol-evidence-proposer",
        workflow_sha256=WORKFLOW_SHA256,
        generated_at=generated_at,
    )


def _duplicate_visibility_queue() -> list[dict[str, str]]:
    first = _review(queue_kind="visibility")
    source = {
        field: first[field]
        for field in ("symbol", "action_type", "ex_date", "purpose", "reason")
    }
    return build_review_rows("visibility", [source, copy.deepcopy(source)])


def _authority_free(record: dict[str, object]) -> dict[str, object]:
    value = copy.deepcopy(record)
    value.pop("proposal_id")
    value.pop("generated_at")
    return value


def test_proposal_id_excludes_generated_at_but_records_preserve_timestamp():
    first = _proposal(generated_at="2024-02-01T00:00:00Z")
    second = _proposal(generated_at="2024-02-02T00:00:00Z")

    assert first["proposal_id"] == second["proposal_id"]
    assert first["generated_at"] == "2024-02-01T00:00:00Z"
    assert second["generated_at"] == "2024-02-02T00:00:00Z"
    assert first["proposal_id"] == hashlib.sha256(
        canonical_json_bytes(_authority_free(first))
    ).hexdigest()


def test_visibility_candidate_remains_manual_and_non_authoritative():
    proposal = _proposal()

    assert proposal["schema_version"] == "corporate-action-ai-proposal-v1"
    assert proposal["proposal_only"] is True
    assert proposal["proposal_status"] == "MANUAL_REQUIRED"
    assert proposal["rationale"] == [
        "ANNOUNCEMENT_CANDIDATES_REQUIRE_HUMAN_SELECTION"
    ]
    assert proposal["evidence_index"]["announcement_candidates"] == [_candidate()]
    assert proposal["retained_candidate_evidence"] == []
    assert proposal["factor_worksheet"] is None


def test_retained_candidate_manifest_is_bound_without_becoming_authority():
    review = _review()
    manifest = _candidate_manifest(review)

    proposal = build_ai_proposal(
        review_row=review,
        evidence_index={
            "index_row": _index(review),
            "retained_candidate_manifest": manifest,
        },
        factor_worksheet=None,
        model_id="model",
        workflow_sha256=WORKFLOW_SHA256,
        generated_at="2024-02-01T00:00:02Z",
    )

    assert proposal["proposal_only"] is True
    assert proposal["proposal_status"] == "MANUAL_REQUIRED"
    assert proposal["retained_candidate_evidence"] == manifest["records"]
    assert "decision" not in proposal["retained_candidate_evidence"][0]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda record: record.update({"review_id": "0" * 64}), "candidate"),
        (lambda record: record.update({"candidate_url": "https://example.com/x.pdf"}), "candidate"),
        (lambda record: record.update({"attachment_sha256": "E" * 64}), "SHA-256"),
        (lambda record: record.update({"retrieved_at": "yesterday"}), "timestamp"),
        (lambda record: record.update({"decision": "CONFIRMED"}), "authority"),
    ],
)
def test_retained_candidate_manifest_fails_closed_on_stale_or_invalid_binding(
    mutation,
    message,
):
    review = _review()
    manifest = _candidate_manifest(review)
    mutation(manifest["records"][0])

    with pytest.raises(AIProposalError, match=message):
        build_ai_proposal(
            review_row=review,
            evidence_index={
                "index_row": _index(review),
                "retained_candidate_manifest": manifest,
            },
            factor_worksheet=None,
            model_id="model",
            workflow_sha256=WORKFLOW_SHA256,
            generated_at="2024-02-01T00:00:02Z",
        )


def test_visibility_without_candidate_has_no_safe_proposal():
    proposal = _proposal(with_candidate=False)

    assert proposal["proposal_status"] == "NO_SAFE_PROPOSAL"
    assert proposal["rationale"] == ["NO_COMPATIBLE_ANNOUNCEMENT_CANDIDATE"]


def test_complete_factor_worksheet_is_only_an_ai_proposal():
    proposal = _proposal(queue_kind="factor", with_candidate=False)

    assert proposal["proposal_status"] == "AI_PROPOSED"
    assert proposal["rationale"] == [
        "FACTOR_WORKSHEET_COMPLETE_HUMAN_ADOPTION_REQUIRED"
    ]
    assert proposal["factor_worksheet"]["candidate_factor"] == "0.960000000000"
    with pytest.raises(CorporateActionError, match="verified audit"):
        apply_reviewed_factor_overrides([], proposal)


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("review", "reviewer_id", "ai-reviewer"),
        ("index", "decision", "CONFIRMED"),
        ("candidate", "canonical_decision", "CONFIRMED"),
        ("worksheet", "approved", True),
        ("worksheet_nested", "adjustment_factor", "0.96"),
    ],
)
def test_inputs_reject_unknown_or_authority_fields(target, field, value):
    review = _review(queue_kind="factor")
    index = _index(review, with_candidate=False)
    worksheet = _worksheet(review)
    if target == "review":
        review[field] = value
    elif target == "index":
        index[field] = value
    elif target == "candidate":
        index["announcement_candidates"] = [_candidate()]
        index["announcement_candidates"][0][field] = value
        index["candidate_resolution"] = "AMBIGUOUS_REVIEW_REQUIRED"
    elif target == "worksheet":
        worksheet[field] = value
    else:
        worksheet["retained_inputs"]["rights_terms"][field] = value

    with pytest.raises(AIProposalError):
        build_ai_proposal(
            review_row=review,
            evidence_index=index,
            factor_worksheet=worksheet,
            model_id="model",
            workflow_sha256=WORKFLOW_SHA256,
            generated_at="2024-02-01T00:00:00Z",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_id", ""),
        ("model_id", " model "),
        ("workflow_sha256", "F" * 64),
        ("workflow_sha256", "f" * 63),
        ("generated_at", "2024-02-01"),
        ("generated_at", "2024-02-30T00:00:00Z"),
        ("generated_at", "2024-02-01T00:00:00+00:00"),
    ],
)
def test_model_workflow_and_generation_metadata_are_strict(field, value):
    review = _review()
    arguments = {
        "review_row": review,
        "evidence_index": _index(review),
        "factor_worksheet": None,
        "model_id": "model",
        "workflow_sha256": WORKFLOW_SHA256,
        "generated_at": "2024-02-01T00:00:00Z",
    }
    arguments[field] = value

    with pytest.raises(AIProposalError):
        build_ai_proposal(**arguments)


def test_stale_review_id_or_identity_fails_closed():
    review = _review()
    index = _index(review)
    index["review_id"] = "0" * 64

    with pytest.raises(AIProposalError, match="review ID"):
        build_ai_proposal(
            review_row=review,
            evidence_index=index,
            factor_worksheet=None,
            model_id="model",
            workflow_sha256=WORKFLOW_SHA256,
            generated_at="2024-02-01T00:00:00Z",
        )

    index = _index(review)
    index["review_identity"]["purpose"] = "stale purpose"
    with pytest.raises(AIProposalError, match="identity"):
        build_ai_proposal(
            review_row=review,
            evidence_index=index,
            factor_worksheet=None,
            model_id="model",
            workflow_sha256=WORKFLOW_SHA256,
            generated_at="2024-02-01T00:00:00Z",
        )


def test_duplicate_queue_occurrence_builds_and_replays_with_full_context(tmp_path):
    queue = _duplicate_visibility_queue()
    second = queue[1]
    proposal = build_ai_proposal(
        review_row=second,
        review_queue_rows=queue,
        evidence_index=_index(second),
        factor_worksheet=None,
        model_id="model",
        workflow_sha256=WORKFLOW_SHA256,
        generated_at="2024-02-01T00:00:00Z",
    )

    assert proposal["review_id"] == second["review_id"]
    assert proposal["review_queue_context"] == {
        "queue_kind": "visibility",
        "review_rows": queue,
    }
    path = tmp_path / "ai-proposals.jsonl"
    first = append_ai_proposals(path, [proposal])
    replay = append_ai_proposals(path, [copy.deepcopy(proposal)])

    assert first["appended_count"] == 1
    assert replay["appended_count"] == 0
    assert path.read_bytes() == canonical_json_bytes(proposal)


def test_forged_duplicate_occurrence_id_fails_with_full_queue_context():
    queue = _duplicate_visibility_queue()
    forged_queue = copy.deepcopy(queue)
    forged_queue[1]["review_id"] = "0" * 64
    forged = forged_queue[1]

    with pytest.raises(AIProposalError, match="canonical review identity"):
        build_ai_proposal(
            review_row=forged,
            review_queue_rows=forged_queue,
            evidence_index=_index(forged),
            factor_worksheet=None,
            model_id="model",
            workflow_sha256=WORKFLOW_SHA256,
            generated_at="2024-02-01T00:00:00Z",
        )


def test_history_replay_rejects_forged_duplicate_occurrence_context(tmp_path):
    queue = _duplicate_visibility_queue()
    second = queue[1]
    proposal = build_ai_proposal(
        review_row=second,
        review_queue_rows=queue,
        evidence_index=_index(second),
        factor_worksheet=None,
        model_id="model",
        workflow_sha256=WORKFLOW_SHA256,
        generated_at="2024-02-01T00:00:00Z",
    )
    forged = copy.deepcopy(proposal)
    forged["review_id"] = "0" * 64
    forged["evidence_index"]["review_id"] = "0" * 64
    forged["review_queue_context"]["review_rows"][1]["review_id"] = "0" * 64
    forged["proposal_id"] = hashlib.sha256(
        canonical_json_bytes(_authority_free(forged))
    ).hexdigest()
    path = tmp_path / "ai-proposals.jsonl"
    content = canonical_json_bytes(forged)
    path.write_bytes(content)

    with pytest.raises(AIProposalError, match="canonical review identity"):
        append_ai_proposals(path, [])

    assert path.read_bytes() == content


@pytest.mark.parametrize("queue_kind", ["visibility", "factor"])
def test_consistently_repeated_forged_review_id_is_recomputed_and_rejected(queue_kind):
    review = _review(queue_kind=queue_kind)
    review["review_id"] = "0" * 64
    index = _index(review, with_candidate=queue_kind == "visibility")
    worksheet = _worksheet(review) if queue_kind == "factor" else None

    with pytest.raises(AIProposalError, match="canonical review identity"):
        build_ai_proposal(
            review_row=review,
            evidence_index=index,
            factor_worksheet=worksheet,
            model_id="model",
            workflow_sha256=WORKFLOW_SHA256,
            generated_at="2024-02-01T00:00:00Z",
        )


def test_append_recomputes_review_id_in_supplied_history_record(tmp_path):
    proposal = _proposal()
    forged = "0" * 64
    proposal["review_id"] = forged
    proposal["evidence_index"]["review_id"] = forged
    proposal["proposal_id"] = hashlib.sha256(
        canonical_json_bytes(_authority_free(proposal))
    ).hexdigest()
    path = tmp_path / "ai-proposals.jsonl"
    content = canonical_json_bytes(proposal)
    path.write_bytes(content)

    with pytest.raises(AIProposalError, match="canonical review identity"):
        append_ai_proposals(path, [])

    assert path.read_bytes() == content


def test_factor_worksheet_must_match_factor_review_exactly():
    review = _review(queue_kind="factor")
    worksheet = _worksheet(review)
    worksheet["review_id"] = "0" * 64

    with pytest.raises(AIProposalError, match="worksheet review ID"):
        build_ai_proposal(
            review_row=review,
            evidence_index=_index(review, with_candidate=False),
            factor_worksheet=worksheet,
            model_id="model",
            workflow_sha256=WORKFLOW_SHA256,
            generated_at="2024-02-01T00:00:00Z",
        )


def test_nan_anywhere_is_rejected():
    review = _review()
    index = _index(review)
    index["action_source"]["bytes"] = float("nan")

    with pytest.raises(AIProposalError):
        build_ai_proposal(
            review_row=review,
            evidence_index=index,
            factor_worksheet=None,
            model_id="model",
            workflow_sha256=WORKFLOW_SHA256,
            generated_at="2024-02-01T00:00:00Z",
        )


def test_append_writes_only_canonical_json_lines_and_returns_hash(tmp_path):
    path = tmp_path / "proposals" / "ai-proposals.jsonl"
    proposals = [_proposal(), _proposal(queue_kind="factor", with_candidate=False)]

    result = append_ai_proposals(path, proposals)
    expected = b"".join(canonical_json_bytes(value) for value in proposals)

    assert path.read_bytes() == expected
    assert result == {
        "schema_version": "corporate-action-ai-proposal-log-v1",
        "existing_count": 0,
        "appended_count": 2,
        "proposal_count": 2,
        "sha256": hashlib.sha256(expected).hexdigest(),
    }


def test_exact_duplicate_is_idempotent_without_rewriting_history(tmp_path):
    path = tmp_path / "ai-proposals.jsonl"
    proposal = _proposal()
    first = append_ai_proposals(path, [proposal])
    before = path.read_bytes()

    second = append_ai_proposals(path, [copy.deepcopy(proposal)])

    assert path.read_bytes() == before
    assert first["appended_count"] == 1
    assert second["existing_count"] == 1
    assert second["appended_count"] == 0
    assert second["proposal_count"] == 1


def test_same_stable_id_with_new_timestamp_preserves_both_records(tmp_path):
    path = tmp_path / "ai-proposals.jsonl"
    first = _proposal(generated_at="2024-02-01T00:00:00Z")
    second = _proposal(generated_at="2024-02-02T00:00:00Z")

    result = append_ai_proposals(path, [first, second])
    records = [json.loads(line) for line in path.read_text().splitlines()]

    assert first["proposal_id"] == second["proposal_id"]
    assert [record["generated_at"] for record in records] == [
        "2024-02-01T00:00:00Z",
        "2024-02-02T00:00:00Z",
    ]
    assert result["appended_count"] == 2


def test_same_id_with_conflicting_authority_free_content_fails_without_append(tmp_path):
    path = tmp_path / "ai-proposals.jsonl"
    original = _proposal()
    append_ai_proposals(path, [original])
    before = path.read_bytes()
    conflict = copy.deepcopy(original)
    conflict["model_id"] = "different-model"

    with pytest.raises(AIProposalError, match="proposal ID"):
        append_ai_proposals(path, [conflict])

    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "existing",
    [
        b'{"z":1, "a":2}\n',
        b'{"a":2,"z":1}',
        b"\n",
        b'{"value":NaN}\n',
        b"not-json\n",
    ],
)
def test_noncanonical_existing_history_fails_without_change(tmp_path, existing):
    path = tmp_path / "ai-proposals.jsonl"
    path.write_bytes(existing)

    with pytest.raises(AIProposalError, match="history"):
        append_ai_proposals(path, [_proposal()])

    assert path.read_bytes() == existing


def test_existing_record_with_invalid_schema_fails_without_change(tmp_path):
    path = tmp_path / "ai-proposals.jsonl"
    invalid = _proposal()
    invalid["schema_version"] = "corporate-action-ai-proposal-v0"
    content = canonical_json_bytes(invalid)
    path.write_bytes(content)

    with pytest.raises(AIProposalError):
        append_ai_proposals(path, [_proposal()])

    assert path.read_bytes() == content


def test_append_rejects_symlink_destination(tmp_path):
    target = tmp_path / "target.jsonl"
    target.write_bytes(canonical_json_bytes(_proposal()))
    link = tmp_path / "ai-proposals.jsonl"
    link.symlink_to(target)

    with pytest.raises(AIProposalError, match="regular file"):
        append_ai_proposals(link, [_proposal(generated_at="2024-02-02T00:00:00Z")])

    assert target.read_bytes() == canonical_json_bytes(_proposal())


@pytest.mark.parametrize("symlink_depth", [0, 1])
def test_append_rejects_symlinked_parent_or_ancestor_components(
    tmp_path,
    symlink_depth,
):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    if symlink_depth == 0:
        symlink = tmp_path / "linked-parent"
        destination = symlink / "ai-proposals.jsonl"
    else:
        safe = tmp_path / "safe"
        safe.mkdir()
        symlink = safe / "linked-ancestor"
        destination = symlink / "nested" / "ai-proposals.jsonl"
    symlink.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(AIProposalError, match="symlink"):
        append_ai_proposals(destination, [_proposal()])

    assert list(real_parent.iterdir()) == []


def test_relative_path_rejects_symlinked_ancestor_component(tmp_path, monkeypatch):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    (tmp_path / "linked-parent").symlink_to(real_parent, target_is_directory=True)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(AIProposalError, match="symlink"):
        append_ai_proposals(
            Path("linked-parent/nested/ai-proposals.jsonl"),
            [_proposal()],
        )

    assert list(real_parent.iterdir()) == []


def test_append_rejects_hard_link_destination_without_touching_other_name(tmp_path):
    target = tmp_path / "other-artifact.jsonl"
    original = canonical_json_bytes(_proposal())
    target.write_bytes(original)
    link = tmp_path / "ai-proposals.jsonl"
    link.hardlink_to(target)

    with pytest.raises(AIProposalError, match="single-link regular file"):
        append_ai_proposals(link, [_proposal(generated_at="2024-02-02T00:00:00Z")])

    assert target.read_bytes() == original
    assert link.read_bytes() == original


def test_path_replacement_while_waiting_for_lock_fails_before_append(
    tmp_path,
    monkeypatch,
):
    from src.reliability import corporate_action_ai_proposals as module

    path = tmp_path / "ai-proposals.jsonl"
    first = _proposal()
    original = canonical_json_bytes(first)
    replacement = canonical_json_bytes(
        _proposal(queue_kind="factor", with_candidate=False)
    )
    path.write_bytes(original)
    replacement_path = tmp_path / "replacement.jsonl"
    replacement_path.write_bytes(replacement)
    witness = tmp_path / "opened-inode.jsonl"
    real_flock = module.fcntl.flock

    def replace_before_lock(descriptor, operation):
        if operation == module.fcntl.LOCK_EX:
            witness.hardlink_to(path)
            module.os.replace(replacement_path, path)
        return real_flock(descriptor, operation)

    monkeypatch.setattr(module.fcntl, "flock", replace_before_lock)

    with pytest.raises(AIProposalError, match="path binding changed"):
        append_ai_proposals(
            path,
            [_proposal(generated_at="2024-02-02T00:00:00Z")],
        )

    assert witness.read_bytes() == original
    assert path.read_bytes() == replacement


def test_append_uses_exclusive_lock_and_fsyncs_file_and_parent(tmp_path, monkeypatch):
    from src.reliability import corporate_action_ai_proposals as module

    path = tmp_path / "ai-proposals.jsonl"
    lock_operations: list[int] = []
    fsync_modes: list[int] = []
    real_flock = module.fcntl.flock
    real_fsync = module.os.fsync

    def record_lock(descriptor, operation):
        lock_operations.append(operation)
        return real_flock(descriptor, operation)

    def record_fsync(descriptor):
        fsync_modes.append(module.os.fstat(descriptor).st_mode)
        return real_fsync(descriptor)

    monkeypatch.setattr(module.fcntl, "flock", record_lock)
    monkeypatch.setattr(module.os, "fsync", record_fsync)

    append_ai_proposals(path, [_proposal()])

    assert lock_operations == [module.fcntl.LOCK_EX, module.fcntl.LOCK_UN]
    assert any(module.stat.S_ISREG(mode) for mode in fsync_modes)
    assert any(module.stat.S_ISDIR(mode) for mode in fsync_modes)


def test_parent_fsync_failure_reports_durability_uncertainty_and_keeps_append(
    tmp_path,
    monkeypatch,
):
    from src.reliability import corporate_action_ai_proposals as module

    path = tmp_path / "ai-proposals.jsonl"
    proposal = _proposal()
    real_fsync = module.os.fsync

    def fail_parent_fsync(descriptor):
        if module.stat.S_ISDIR(module.os.fstat(descriptor).st_mode):
            raise OSError("parent fsync failed")
        return real_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_parent_fsync)

    with pytest.raises(AIProposalDurabilityError, match="destination changed"):
        append_ai_proposals(path, [proposal])

    assert path.read_bytes() == canonical_json_bytes(proposal)


def test_idempotent_noop_does_not_fsync_parent_or_report_destination_changed(
    tmp_path,
    monkeypatch,
):
    from src.reliability import corporate_action_ai_proposals as module

    path = tmp_path / "ai-proposals.jsonl"
    proposal = _proposal()
    append_ai_proposals(path, [proposal])
    before = path.read_bytes()
    parent_fsync_calls = 0

    def fail_if_called(_path):
        nonlocal parent_fsync_calls
        parent_fsync_calls += 1
        raise OSError("parent fsync should not run for a no-op")

    monkeypatch.setattr(module, "_fsync_parent", fail_if_called)

    result = append_ai_proposals(path, [copy.deepcopy(proposal)])

    assert result["appended_count"] == 0
    assert result["proposal_count"] == 1
    assert parent_fsync_calls == 0
    assert path.read_bytes() == before


def test_failed_write_restores_exact_prior_history(tmp_path, monkeypatch):
    from src.reliability import corporate_action_ai_proposals as module

    path = tmp_path / "ai-proposals.jsonl"
    first = _proposal()
    append_ai_proposals(path, [first])
    before = path.read_bytes()
    real_write_all = module._write_all

    def partial_then_fail(handle, content):
        handle.write(content[:11])
        handle.flush()
        raise OSError("interrupted append")

    monkeypatch.setattr(module, "_write_all", partial_then_fail)
    with pytest.raises(AIProposalError, match="append failed"):
        append_ai_proposals(
            path,
            [_proposal(generated_at="2024-02-02T00:00:00Z")],
        )
    monkeypatch.setattr(module, "_write_all", real_write_all)

    assert path.read_bytes() == before


def test_proposal_workflow_does_not_touch_canonical_csvs(tmp_path):
    visibility = tmp_path / "visibility-reviews.csv"
    factors = tmp_path / "factor-reviews.csv"
    visibility.write_bytes(b"review_id,decision\nabc,PENDING\n")
    factors.write_bytes(b"review_id,decision\ndef,PENDING\n")
    before = (visibility.read_bytes(), factors.read_bytes())

    append_ai_proposals(tmp_path / "ai-proposals.jsonl", [_proposal()])

    assert (visibility.read_bytes(), factors.read_bytes()) == before
