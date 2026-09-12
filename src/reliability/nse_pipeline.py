"""Operator CLI for building and checking NSE reliability bundles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.reliability.nse_bundle import assess_bundle, build_nse_bundle


def _resolve(base: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def apply_generation_blockers(quality: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    result = {**quality, "blockers": list(quality.get("blockers", []))}
    for blocker in blockers:
        if blocker not in result["blockers"]:
            result["blockers"].append(blocker)
    result["ready"] = not result["blockers"]
    return result


def run_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    base = config_path.parent
    config = json.loads(config_path.read_text(encoding="utf-8"))

    def descriptors(name: str) -> list[dict[str, Any]]:
        output = []
        for item in config.get(name, []):
            output.append({**item, "path": _resolve(base, item["path"])})
        return output

    output_path = _resolve(base, config.get("output", "nse-bundle.json"))
    quality_path = _resolve(base, config.get("quality_report", "nse-quality.json"))
    bundle = build_nse_bundle(
        security_snapshots=descriptors("security_snapshots"),
        bhavcopies=descriptors("bhavcopies"),
        corporate_actions=descriptors("corporate_actions"),
        financials=[_resolve(base, value) for value in config.get("financials", [])],
        business_classifications=[
            _resolve(base, value) for value in config.get("business_classifications", [])
        ],
        output=output_path,
    )
    quality = assess_bundle(
        bundle,
        as_of=config["as_of"],
        max_price_age_days=int(config.get("max_price_age_days", 7)),
        max_fundamental_age_days=int(config.get("max_fundamental_age_days", 200)),
    )
    quality = apply_generation_blockers(quality, config.get("generation_blockers", []))
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(json.dumps(quality, indent=2, sort_keys=True), encoding="utf-8")
    return {"bundle": str(output_path), "quality_report": str(quality_path), "quality": quality}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a point-in-time NSE reliability bundle")
    parser.add_argument("config", help="JSON source configuration")
    args = parser.parse_args()
    result = run_config(args.config)
    print(json.dumps(result, indent=2))
    if not result["quality"]["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
