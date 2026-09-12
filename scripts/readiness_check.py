"""Read-only activation preflight for Telegram and personal broker use."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.control_server import _release_status


def _result(status: dict, required: set[str]) -> tuple[bool, dict]:
    channels = {
        "telegram": status.get("telegram_recommendations") is True,
        "broker": status.get("broker_orders") is True,
    }
    missing = [name for name in sorted(required) if not channels[name]]
    return not missing, {
        "ok": not missing,
        "required_channels": sorted(required),
        "missing_channels": missing,
        "mode": status.get("mode"),
        "execution_mode": status.get("execution_mode"),
        "live_symbol": status.get("live_symbol"),
        "telegram": channels["telegram"],
        "broker": channels["broker"],
        "telegram_reason": status.get("telegram_reason"),
        "broker_reason": status.get("broker_reason"),
        "broker_exit_reason": status.get("broker_exit_reason"),
        "personal_live_trading_acknowledged": status.get(
            "personal_live_trading_acknowledged", False
        ),
        "broker_credentials_configured": status.get(
            "broker_credentials_configured", False
        ),
        "broker_session": status.get("broker_session", {}),
        "blockers": status.get("blockers", []),
        "operational_kill_switch": status.get("operational_kill_switch", False),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require", choices=("telegram", "broker"), action="append",
        help="channel that must be ready; defaults to both",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    required = set(args.require or ("telegram", "broker"))
    ready, report = _result(_release_status(), required)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print("Boro activation preflight: READY" if ready else "Boro activation preflight: BLOCKED")
        print(f"Required: {', '.join(report['required_channels'])}")
        print(f"Telegram: {'ready' if report['telegram'] else 'blocked'}")
        if report.get("telegram_reason"):
            print(f"Telegram reason: {report['telegram_reason']}")
        print(f"Broker: {'ready' if report['broker'] else 'blocked'} ({report['live_symbol']})")
        if report.get("broker_reason"):
            print(f"Broker reason: {report['broker_reason']}")
        print(
            "Private live acknowledgement: "
            + ("present" if report["personal_live_trading_acknowledged"] else "missing")
        )
        if report["broker_session"]:
            print(f"Broker session: {report['broker_session'].get('reason', 'unknown')}")
        if report["blockers"]:
            print("Blockers: " + ", ".join(report["blockers"]))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
