import hashlib
import json
from pathlib import Path

import pytest

from src.reliability.corporate_action_catalogue_remediation import (
    CatalogueRemediationError,
    remediate_catalogue,
)


def _record(path: Path, *, status: str = "downloaded", sha: str | None = None):
    content = path.read_bytes()
    return {
        "available_at": "2024-01-10T10:00:00Z",
        "bytes": len(content),
        "kind": "corporate_actions",
        "params": {
            "from_date": "01-01-2024",
            "index": "equities",
            "to_date": "31-01-2024",
        },
        "path": str(path),
        "sha256": sha or hashlib.sha256(content).hexdigest(),
        "status": status,
        "url": "https://www.nseindia.com/api/corporates-corporateActions",
    }


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_remediation_preserves_source_and_records_exact_duplicate(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("[]")
    source = tmp_path / "source.jsonl"
    row = _record(snapshot)
    duplicate = {**row, "status": "cached", "available_at": "2024-01-11T10:00:00Z"}
    _write(source, [row, duplicate])
    original = source.read_bytes()

    result = remediate_catalogue(
        source,
        output_path=tmp_path / "remediated.jsonl",
        manifest_path=tmp_path / "remediation.json",
    )

    assert source.read_bytes() == original
    assert result["removed_duplicate_count"] == 1
    assert result["proposal_only"] is True
    assert result["input_record_count"] == 2
    assert result["output_record_count"] == 1
    assert len((tmp_path / "remediated.jsonl").read_text().splitlines()) == 1


def test_remediation_rejects_conflicting_window(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("[]")
    source = tmp_path / "source.jsonl"
    row = _record(snapshot)
    conflict = {**row, "sha256": "0" * 64}
    _write(source, [row, conflict])

    with pytest.raises(CatalogueRemediationError, match="conflicting eligible"):
        remediate_catalogue(
            source,
            output_path=tmp_path / "remediated.jsonl",
            manifest_path=tmp_path / "remediation.json",
        )
    assert not (tmp_path / "remediated.jsonl").exists()


def test_remediation_rejects_malformed_input(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text('{"status":"failed"}\nnot-json\n')

    with pytest.raises(CatalogueRemediationError, match="invalid JSON"):
        remediate_catalogue(
            source,
            output_path=tmp_path / "remediated.jsonl",
            manifest_path=tmp_path / "remediation.json",
        )
