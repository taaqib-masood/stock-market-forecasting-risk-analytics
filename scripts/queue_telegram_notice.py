"""Queue one consent-bound Telegram operational notice.

This is intended for scheduled/CI automation. It never accepts a recipient ID;
the active Telegram audience registry and recommendation delivery gates decide
whether anything is queued or sent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.notify import queue_audience_message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-id", required=True)
    parser.add_argument("--text", required=True)
    args = parser.parse_args(argv)
    try:
        result = queue_audience_message(args.text, args.signal_id)
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if result.get("queued", 0) or result.get("created", 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
