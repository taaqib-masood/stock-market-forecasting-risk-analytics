import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import src.reliability.corporate_action_ai_proposals as cli_module
from src.reliability.corporate_action_review_packet import export_review_packet
from src.reliability.corporate_action_reviews import build_review_rows
from src.reliability.preregistration import canonical_json_bytes


MODULE = "src.reliability.corporate_action_ai_proposals"
WORKFLOW_SHA256 = "a" * 64
GENERATED_AT = "2026-08-01T15:00:00Z"
SECRET_TEXT = "PRIVATE-VALIDATION-VALUE-DO-NOT-PRINT"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_record(path: Path, *, kind: str) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "available_at": "2024-01-10T10:00:00Z",
        "bytes": len(content),
        "kind": kind,
        "params": {
            "from_date": "01-01-2024",
            "index": "equities",
            "to_date": "31-01-2024",
        },
        "path": str(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "status": "downloaded",
    }


def _fixture(tmp_path: Path) -> dict[str, Path]:
    retained_root = tmp_path / "retained"
    retained_root.mkdir()
    actions_path = retained_root / "actions.json"
    announcements_path = retained_root / "announcements.json"
    actions_path.write_text(
        json.dumps([
            {
                "symbol": "ACME",
                "series": "EQ",
                "subject": f"Interim Dividend {SECRET_TEXT}",
                "exDate": "15-Jan-2024",
                "recDate": "16-Jan-2024",
            },
            {
                "symbol": "RIGHTSCO",
                "series": "EQ",
                "subject": "Rights 1:4 @ Rs 80",
                "exDate": "15-Jan-2024",
                "recDate": "16-Jan-2024",
            },
        ]),
        encoding="utf-8",
    )
    announcements_path.write_text("[]", encoding="utf-8")
    catalogue_path = retained_root / "source-catalogue.jsonl"
    catalogue_path.write_text(
        "".join(
            json.dumps(record, sort_keys=True) + "\n"
            for record in (
                _source_record(actions_path, kind="corporate_actions"),
                _source_record(
                    announcements_path,
                    kind="corporate_announcements",
                ),
            )
        ),
        encoding="utf-8",
    )

    visibility = {
        "symbol": "ACME",
        "action_type": "DIVIDEND",
        "ex_date": "2024-01-15",
        "purpose": f"Interim Dividend {SECRET_TEXT}",
        "reason": "snapshot_retrieval",
    }
    factor = {
        "symbol": "RIGHTSCO",
        "action_type": "RIGHTS",
        "ex_date": "2024-01-15",
        "purpose": "Rights 1:4 @ Rs 80",
        "reason": "reviewed adjustment factor required",
    }
    baseline_path = retained_root / "baseline.json"
    baseline_path.write_bytes(canonical_json_bytes({
        "visibility_review_queue": [visibility],
        "factor_review_queue": [factor],
    }))
    packet_dir = tmp_path / "packet"
    export_review_packet(baseline_path, packet_dir)

    factor_review = build_review_rows("factor", [factor])[0]
    rights_terms_path = retained_root / "rights-terms.txt"
    rights_terms_path.write_text(factor["purpose"], encoding="utf-8")
    price_path = retained_root / "cum-rights-price.txt"
    price_path.write_text("100", encoding="utf-8")
    retained_inputs_path = retained_root / "retained-inputs.jsonl"
    retained_inputs_path.write_bytes(canonical_json_bytes({
        "review_id": factor_review["review_id"],
        "retained_inputs": {
            "rights_terms": {
                "value": factor["purpose"],
                "path": str(rights_terms_path),
                "sha256": _sha256(rights_terms_path),
                "available_at": "2024-01-10T10:00:00Z",
            },
            "cum_rights_price": {
                "value": "100",
                "path": str(price_path),
                "sha256": _sha256(price_path),
                "available_at": "2024-01-10T10:00:00Z",
            },
        },
    }))
    return {
        "catalogue": catalogue_path,
        "baseline": baseline_path,
        "packet": packet_dir,
        "proposal": tmp_path / "proposal",
        "retained_inputs": retained_inputs_path,
    }


def _run(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1])
    return subprocess.run(
        [sys.executable, "-m", MODULE, *arguments],
        cwd=cwd or Path(__file__).parents[1],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _common(fixture: dict[str, Path]) -> list[str]:
    return [
        "--proposal-root",
        str(fixture["proposal"]),
        "--packet-dir",
        str(fixture["packet"]),
    ]


def _build_index(fixture: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return _run(
        "build-index",
        *_common(fixture),
        "--catalogue",
        str(fixture["catalogue"]),
        "--baseline-report",
        str(fixture["baseline"]),
    )


def _retain_candidates(fixture: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return _run(
        "retain-candidates",
        *_common(fixture),
        "--allowed-host",
        "nsearchives.nseindia.com",
    )


def _build_worksheets(fixture: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return _run(
        "build-worksheets",
        *_common(fixture),
        "--baseline-report",
        str(fixture["baseline"]),
        "--retained-inputs",
        str(fixture["retained_inputs"]),
    )


def _append_proposals(fixture: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return _run(
        "append-proposals",
        *_common(fixture),
        "--baseline-report",
        str(fixture["baseline"]),
        "--model-id",
        "isolated-test-model",
        "--workflow-sha256",
        WORKFLOW_SHA256,
        "--generated-at",
        GENERATED_AT,
    )


def _make_verify_ready(fixture: dict[str, Path]) -> None:
    for result in (
        _build_index(fixture),
        _retain_candidates(fixture),
        _build_worksheets(fixture),
        _append_proposals(fixture),
    ):
        assert result.returncode == 0, result.stderr


def _load_cli_manifest(fixture: dict[str, Path]) -> dict[str, object]:
    return json.loads((fixture["proposal"] / "manifest.json").read_bytes())


def _write_cli_manifest(fixture: dict[str, Path], manifest: dict[str, object]) -> None:
    (fixture["proposal"] / "manifest.json").write_bytes(
        canonical_json_bytes(manifest)
    )


def _replace_candidate_manifest(
    fixture: dict[str, Path],
    value: dict[str, object],
) -> None:
    content = canonical_json_bytes(value)
    digest = hashlib.sha256(content).hexdigest()
    relative = Path("evidence") / "manifests" / "sha256" / digest[:2] / f"{digest}.json"
    path = fixture["proposal"] / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    manifest = _load_cli_manifest(fixture)
    manifest["artifacts"]["candidate_manifest"] = {
        "path": relative.as_posix(),
        "sha256": digest,
        "count": len(value.get("records", [])),
        "status": "CURRENT",
    }
    _write_cli_manifest(fixture, manifest)


def _assert_blocked_without_approval_echo(
    result: subprocess.CompletedProcess[str],
) -> dict[str, object]:
    assert result.returncode == 2
    assert result.stdout == ""
    assert "APPROVED" not in result.stderr
    payload = json.loads(result.stderr)
    assert payload["status"] == "BLOCKED"
    return payload


def _assert_safe_output(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.returncode == 0, result.stderr
    assert SECRET_TEXT not in result.stdout
    assert SECRET_TEXT not in result.stderr
    assert "validation_value" not in result.stdout.lower()
    assert "canonical_decision" not in result.stdout.lower()
    payload = json.loads(result.stdout)
    assert payload["status"] == "COMPLETED"
    assert payload["proposal_only"] is True
    assert set(payload) == {
        "schema_version",
        "proposal_only",
        "command",
        "status",
        "artifacts",
        "counts",
        "blocker_categories",
    }
    return payload


def test_cli_round_trip_is_isolated_and_packet_csvs_remain_unchanged(tmp_path):
    fixture = _fixture(tmp_path)
    packet_hashes = {
        name: _sha256(fixture["packet"] / name)
        for name in ("visibility-reviews.csv", "factor-reviews.csv")
    }

    build = _run(
        "build-index",
        *_common(fixture),
        "--catalogue",
        str(fixture["catalogue"]),
        "--baseline-report",
        str(fixture["baseline"]),
    )
    assert _assert_safe_output(build)["counts"] == {
        "factor": 1,
        "total": 2,
        "visibility": 1,
    }

    retain = _run(
        "retain-candidates",
        *_common(fixture),
        "--allowed-host",
        "nsearchives.nseindia.com",
    )
    assert _assert_safe_output(retain)["counts"] == {
        "candidate_records": 0,
        "failed": 0,
        "retained": 0,
    }

    worksheets = _run(
        "build-worksheets",
        *_common(fixture),
        "--baseline-report",
        str(fixture["baseline"]),
        "--retained-inputs",
        str(fixture["retained_inputs"]),
    )
    assert _assert_safe_output(worksheets)["counts"] == {
        "ai_proposed": 1,
        "manual_required": 0,
        "total": 1,
    }

    append = _run(
        "append-proposals",
        *_common(fixture),
        "--baseline-report",
        str(fixture["baseline"]),
        "--model-id",
        "isolated-test-model",
        "--workflow-sha256",
        WORKFLOW_SHA256,
        "--generated-at",
        GENERATED_AT,
    )
    assert _assert_safe_output(append)["counts"] == {
        "appended": 2,
        "existing": 0,
        "total": 2,
    }

    verify = _run("verify", *_common(fixture))
    assert _assert_safe_output(verify)["counts"] == {
        "artifacts": 4,
        "packet_csvs": 2,
        "proposals": 2,
    }

    assert (fixture["proposal"] / "evidence-index.jsonl").is_file()
    assert (fixture["proposal"] / "factor-worksheets.jsonl").is_file()
    assert (fixture["proposal"] / "ai-proposals.jsonl").is_file()
    assert (fixture["proposal"] / "manifest.json").is_file()
    assert packet_hashes == {
        name: _sha256(fixture["packet"] / name)
        for name in packet_hashes
    }


def test_cli_preexisting_part_blocks_before_replacing_output(tmp_path):
    fixture = _fixture(tmp_path)
    fixture["proposal"].mkdir()
    index_path = fixture["proposal"] / "evidence-index.jsonl"
    index_path.write_bytes(b"prior-index\n")
    part = fixture["proposal"] / "nested" / "stale.part"
    part.parent.mkdir()
    part.write_bytes(b"interrupted")
    prior_packet_hashes = {
        name: _sha256(fixture["packet"] / name)
        for name in ("visibility-reviews.csv", "factor-reviews.csv")
    }

    result = _run(
        "build-index",
        *_common(fixture),
        "--catalogue",
        str(fixture["catalogue"]),
        "--baseline-report",
        str(fixture["baseline"]),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error == {
        "blocker_categories": ["PREEXISTING_PART_ARTIFACT"],
        "proposal_only": True,
        "schema_version": "corporate-action-ai-cli-output-v1",
        "status": "BLOCKED",
    }
    assert index_path.read_bytes() == b"prior-index\n"
    assert prior_packet_hashes == {
        name: _sha256(fixture["packet"] / name)
        for name in prior_packet_hashes
    }


def test_cli_rejects_output_root_overlapping_canonical_packet(tmp_path):
    fixture = _fixture(tmp_path)
    result = _run(
        "build-index",
        "--proposal-root",
        str(fixture["packet"] / "proposal-output"),
        "--packet-dir",
        str(fixture["packet"]),
        "--catalogue",
        str(fixture["catalogue"]),
        "--baseline-report",
        str(fixture["baseline"]),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["blocker_categories"] == [
        "ROOT_ISOLATION_VIOLATION"
    ]
    assert not (fixture["packet"] / "proposal-output").exists()


@pytest.mark.parametrize(
    "tampered",
    [
        {
            "schema_version": "corporate-action-candidate-evidence-v999",
            "proposal_only": True,
            "records": [],
        },
        {
            "schema_version": "corporate-action-candidate-evidence-v1",
            "proposal_only": False,
            "records": [],
        },
        {
            "schema_version": "corporate-action-candidate-evidence-v1",
            "proposal_only": True,
            "records": [],
            "nested": {"decision": "APPROVED"},
        },
        {
            "schema_version": "corporate-action-candidate-evidence-v1",
            "proposal_only": True,
            "records": [{"status": "APPROVED"}],
        },
    ],
    ids=("schema", "proposal-only", "authority", "status"),
)
def test_verify_strictly_rejects_tampered_candidate_manifest(
    tmp_path,
    tampered,
):
    fixture = _fixture(tmp_path)
    _make_verify_ready(fixture)
    _replace_candidate_manifest(fixture, tampered)

    result = _run("verify", *_common(fixture))

    payload = _assert_blocked_without_approval_echo(result)
    assert payload["blocker_categories"] == ["CANDIDATE_MANIFEST_REJECTED"]


@pytest.mark.parametrize("retained_rows", [0, 1], ids=("empty", "incomplete"))
def test_verify_requires_proposals_for_every_current_index_review_id(
    tmp_path,
    retained_rows,
):
    fixture = _fixture(tmp_path)
    _make_verify_ready(fixture)
    proposal_path = fixture["proposal"] / "ai-proposals.jsonl"
    rows = proposal_path.read_bytes().splitlines(keepends=True)
    content = b"".join(rows[:retained_rows])
    proposal_path.write_bytes(content)
    manifest = _load_cli_manifest(fixture)
    manifest["artifacts"]["ai_proposals"]["sha256"] = hashlib.sha256(
        content
    ).hexdigest()
    manifest["artifacts"]["ai_proposals"]["count"] = retained_rows
    _write_cli_manifest(fixture, manifest)

    result = _run("verify", *_common(fixture))

    assert _assert_blocked_without_approval_echo(result)["blocker_categories"] == [
        "PROPOSAL_SET_MISMATCH"
    ]


def test_verify_rejects_authoritative_artifact_status_without_echoing_it(tmp_path):
    fixture = _fixture(tmp_path)
    _make_verify_ready(fixture)
    manifest = _load_cli_manifest(fixture)
    manifest["artifacts"]["evidence_index"]["status"] = "APPROVED"
    _write_cli_manifest(fixture, manifest)

    result = _run("verify", *_common(fixture))

    assert _assert_blocked_without_approval_echo(result)["blocker_categories"] == [
        "STALE_OR_MALFORMED_MANIFEST"
    ]


@pytest.mark.parametrize("max_bytes", [25_000_001, 100_000_000, 0, -1])
def test_retain_candidates_rejects_out_of_policy_max_bytes(tmp_path, max_bytes):
    fixture = _fixture(tmp_path)
    assert _build_index(fixture).returncode == 0

    result = _run(
        "retain-candidates",
        *_common(fixture),
        "--allowed-host",
        "nsearchives.nseindia.com",
        "--max-bytes",
        str(max_bytes),
    )

    assert _assert_blocked_without_approval_echo(result)["blocker_categories"] == [
        "MAX_BYTES_OUT_OF_POLICY"
    ]
    assert "candidate_manifest" not in _load_cli_manifest(fixture)["artifacts"]


def test_retain_candidates_accepts_policy_ceiling_without_network(tmp_path):
    fixture = _fixture(tmp_path)
    assert _build_index(fixture).returncode == 0

    result = _run(
        "retain-candidates",
        *_common(fixture),
        "--allowed-host",
        "nsearchives.nseindia.com",
        "--max-bytes",
        "25000000",
    )

    assert _assert_safe_output(result)["counts"]["candidate_records"] == 0


@pytest.mark.parametrize(
    "command",
    [
        "build-index",
        "retain-candidates",
        "build-worksheets",
        "append-proposals",
        "verify",
    ],
)
def test_every_command_fails_before_work_when_any_stale_part_exists(
    tmp_path,
    command,
):
    fixture = _fixture(tmp_path)
    if command != "build-index":
        assert _build_index(fixture).returncode == 0
    if command in {"append-proposals", "verify"}:
        assert _retain_candidates(fixture).returncode == 0
        assert _build_worksheets(fixture).returncode == 0
    if command == "verify":
        assert _append_proposals(fixture).returncode == 0

    part = fixture["proposal"] / "nested" / f"{command}.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"stale")
    manifest_before = (
        (fixture["proposal"] / "manifest.json").read_bytes()
        if (fixture["proposal"] / "manifest.json").exists()
        else None
    )
    arguments = {
        "build-index": [
            "build-index",
            *_common(fixture),
            "--catalogue",
            str(fixture["catalogue"]),
            "--baseline-report",
            str(fixture["baseline"]),
        ],
        "retain-candidates": [
            "retain-candidates",
            *_common(fixture),
            "--allowed-host",
            "nsearchives.nseindia.com",
        ],
        "build-worksheets": [
            "build-worksheets",
            *_common(fixture),
            "--baseline-report",
            str(fixture["baseline"]),
            "--retained-inputs",
            str(fixture["retained_inputs"]),
        ],
        "append-proposals": [
            "append-proposals",
            *_common(fixture),
            "--baseline-report",
            str(fixture["baseline"]),
            "--model-id",
            "isolated-test-model",
            "--workflow-sha256",
            WORKFLOW_SHA256,
            "--generated-at",
            GENERATED_AT,
        ],
        "verify": ["verify", *_common(fixture)],
    }[command]

    result = _run(*arguments)

    assert _assert_blocked_without_approval_echo(result)["blocker_categories"] == [
        "PREEXISTING_PART_ARTIFACT"
    ]
    if manifest_before is not None:
        assert (fixture["proposal"] / "manifest.json").read_bytes() == manifest_before


def test_append_rejects_changed_baseline_before_mutating_append_log(tmp_path):
    fixture = _fixture(tmp_path)
    _make_verify_ready(fixture)
    proposal_path = fixture["proposal"] / "ai-proposals.jsonl"
    proposal_before = proposal_path.read_bytes()

    changed_baseline = tmp_path / "changed-baseline.json"
    value = json.loads(fixture["baseline"].read_bytes())
    value["factor_review_queue"][0]["reason"] = "changed after index build"
    changed_baseline.write_bytes(canonical_json_bytes(value))

    result = _run(
        "append-proposals",
        *_common(fixture),
        "--baseline-report",
        str(changed_baseline),
        "--model-id",
        "isolated-test-model",
        "--workflow-sha256",
        WORKFLOW_SHA256,
        "--generated-at",
        GENERATED_AT,
    )

    assert _assert_blocked_without_approval_echo(result)["blocker_categories"] == [
        "UPSTREAM_INPUT_BINDING_CHANGED"
    ]
    assert proposal_path.read_bytes() == proposal_before


def test_root_replacement_during_build_never_writes_through_symlink(
    tmp_path,
    monkeypatch,
    capsys,
):
    fixture = _fixture(tmp_path)
    fixture["proposal"].mkdir()
    displaced = tmp_path / "displaced-root"
    outside = tmp_path / "outside"
    outside.mkdir()
    original_build = cli_module.build_evidence_index

    def replace_root_after_build(**kwargs):
        rows = original_build(**kwargs)
        fixture["proposal"].rename(displaced)
        fixture["proposal"].symlink_to(outside, target_is_directory=True)
        return rows

    monkeypatch.setattr(
        cli_module,
        "build_evidence_index",
        replace_root_after_build,
    )
    exit_code = cli_module.main([
        "build-index",
        *_common(fixture),
        "--catalogue",
        str(fixture["catalogue"]),
        "--baseline-report",
        str(fixture["baseline"]),
    ])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["blocker_categories"] == [
        "ROOT_BINDING_CHANGED"
    ]
    assert list(outside.iterdir()) == []


def test_concurrent_build_index_commands_serialize_manifest_updates(tmp_path):
    fixture = _fixture(tmp_path)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: _build_index(fixture), range(4)))

    assert [result.returncode for result in results] == [0, 0, 0, 0]
    for result in results:
        _assert_safe_output(result)
    manifest = _load_cli_manifest(fixture)
    index_record = manifest["artifacts"]["evidence_index"]
    index_path = fixture["proposal"] / index_record["path"]
    assert index_record["sha256"] == _sha256(index_path)
    assert index_record["count"] == 2


def test_verify_rejects_duplicate_proposal_rows(tmp_path):
    fixture = _fixture(tmp_path)
    _make_verify_ready(fixture)
    proposal_path = fixture["proposal"] / "ai-proposals.jsonl"
    rows = proposal_path.read_bytes().splitlines(keepends=True)
    content = rows[0] + rows[0]
    proposal_path.write_bytes(content)
    manifest = _load_cli_manifest(fixture)
    manifest["artifacts"]["ai_proposals"]["sha256"] = hashlib.sha256(
        content
    ).hexdigest()
    manifest["artifacts"]["ai_proposals"]["count"] = 2
    _write_cli_manifest(fixture, manifest)

    result = _run("verify", *_common(fixture))

    assert _assert_blocked_without_approval_echo(result)["blocker_categories"] == [
        "PROPOSAL_SET_MISMATCH"
    ]


def test_verify_rechecks_retained_attachment_bytes(tmp_path):
    evidence = tmp_path / "evidence" / "sha256" / "aa"
    evidence.mkdir(parents=True)
    attachment = evidence / ("a" * 64 + ".pdf")
    attachment.write_bytes(b"%PDF-test")
    record = {
        "status": "RETAINED",
        "attachment_path": "sha256/aa/" + ("a" * 64) + ".pdf",
        "attachment_sha256": "b" * 64,
        "byte_count": 999,
    }

    with pytest.raises(cli_module.AIProposalCLIError) as error:
        cli_module._verify_retained_attachments(
            tmp_path,
            {"records": [record]},
        )

    assert error.value.category == "ARTIFACT_BINDING_MISMATCH"
