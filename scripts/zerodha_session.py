"""Complete the backend-only Zerodha login session exchange."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.broker_gateway import (
    BrokerOrderError,
    ZerodhaBroker,
    _access_token_file,
    persist_access_token,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or inspect a Kite session")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("login-url", help="print the URL to complete Zerodha login")
    exchange = sub.add_parser("exchange", help="exchange a redirect request_token")
    exchange.add_argument("request_token")
    args = parser.parse_args()
    broker = ZerodhaBroker()
    try:
        if args.action == "login-url":
            print(broker.login_url())
            return 0
        data = broker.exchange_request_token(args.request_token)
        persist_access_token(data["access_token"])
        print("# Short-lived Kite token persisted owner-only; it expires at the next 6 AM.")
        print(f"# Token file: {_access_token_file()}")
        print(json.dumps({
            "user_id": data.get("user_id"),
            "login_time": data.get("login_time"),
            "exchanges": data.get("exchanges", []),
        }))
        return 0
    except BrokerOrderError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
