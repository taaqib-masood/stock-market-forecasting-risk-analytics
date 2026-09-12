"""Register the Telegram bot webhook for consent commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.telegram_provider import register_webhook as provider_register_webhook


def register_webhook(token: str, webhook_url: str, secret: str) -> dict:
    # Compatibility wrapper for callers that imported the old helper directly.
    os.environ["TELEGRAM_TOKEN"] = token
    os.environ["TELEGRAM_WEBHOOK_SECRET"] = secret
    result = provider_register_webhook(webhook_url)
    if not result.get("ok"):
        raise RuntimeError(", ".join(result.get("blockers", ["Telegram rejected webhook"])))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "webhook_url",
        nargs="?",
        default=os.environ.get("TELEGRAM_WEBHOOK_URL", ""),
        help=(
            "public HTTPS URL ending in /telegram/webhook "
            "(defaults to TELEGRAM_WEBHOOK_URL)"
        ),
    )
    args = parser.parse_args()
    try:
        print(json.dumps(register_webhook(
            os.environ.get("TELEGRAM_TOKEN", ""),
            args.webhook_url,
            os.environ.get("TELEGRAM_WEBHOOK_SECRET", ""),
        )))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
