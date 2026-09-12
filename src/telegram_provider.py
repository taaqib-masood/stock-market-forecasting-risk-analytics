"""Telegram Bot API health checks and consent-webhook registration."""

from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


class TelegramProviderError(RuntimeError):
    """Telegram provider returned an unusable response."""


def _api_call(token: str, method: str) -> dict:
    request = Request(f"https://api.telegram.org/bot{token}/{method}")
    try:
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise TelegramProviderError(f"TELEGRAM_API_UNAVAILABLE:{type(error).__name__}") from error
    if result.get("ok") is not True or not isinstance(result.get("result"), dict):
        raise TelegramProviderError("TELEGRAM_API_REJECTED")
    return result["result"]


def _api_form_call(token: str, method: str, fields: dict[str, str]) -> object:
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise TelegramProviderError(f"TELEGRAM_API_UNAVAILABLE:{type(error).__name__}") from error
    if result.get("ok") is not True:
        raise TelegramProviderError("TELEGRAM_API_REJECTED")
    return result.get("result")


def _valid_webhook_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and parsed.path.rstrip("/") == "/telegram/webhook"


def webhook_secret_is_valid(value: str) -> bool:
    """Validate Telegram's secret-token character and length contract."""
    secret = str(value or "").strip()
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret))


def register_webhook(webhook_url: str | None = None) -> dict[str, object]:
    """Register the configured consent webhook without returning any secret."""
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    url = str(webhook_url or os.environ.get("TELEGRAM_WEBHOOK_URL", "")).strip()
    if not token:
        return {"ok": False, "blockers": ["TELEGRAM_TOKEN_MISSING"]}
    if len(secret) < 16 or not webhook_secret_is_valid(secret):
        return {"ok": False, "blockers": ["TELEGRAM_WEBHOOK_SECRET_INVALID"]}
    if not _valid_webhook_url(url):
        return {"ok": False, "blockers": ["TELEGRAM_WEBHOOK_URL_INVALID"]}
    try:
        _api_form_call(token, "setWebhook", {
            "url": url,
            "secret_token": secret,
            "allowed_updates": json.dumps(["message"], separators=(",", ":")),
        })
    except TelegramProviderError as error:
        return {"ok": False, "blockers": [str(error).split(":", 1)[0]]}
    return {"ok": True, "webhook_url": url}


def provider_status() -> dict[str, object]:
    """Return secret-free Bot API/webhook health for an operator cockpit."""
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    secret_configured = bool(os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip())
    expected_url = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip()
    report: dict[str, object] = {
        "ok": False,
        "token_configured": bool(token),
        "token_valid": False,
        "secret_configured": secret_configured,
        "bot_username": None,
        "webhook": {
            "configured_url": expected_url or None,
            "actual_url": None,
            "matches": False,
            "pending_update_count": 0,
            "last_error": False,
        },
        "blockers": [],
    }
    blockers = report["blockers"]
    assert isinstance(blockers, list)
    if not token:
        blockers.append("TELEGRAM_TOKEN_MISSING")
        return report
    if not secret_configured:
        blockers.append("TELEGRAM_WEBHOOK_SECRET_MISSING")
    elif not webhook_secret_is_valid(os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")):
        blockers.append("TELEGRAM_WEBHOOK_SECRET_INVALID")
    if expected_url and not _valid_webhook_url(expected_url):
        blockers.append("TELEGRAM_WEBHOOK_URL_INVALID")
    elif not expected_url:
        blockers.append("TELEGRAM_WEBHOOK_URL_MISSING")
    try:
        bot = _api_call(token, "getMe")
        report["token_valid"] = True
        report["bot_username"] = bot.get("username")
        webhook = _api_call(token, "getWebhookInfo")
        actual_url = str(webhook.get("url", ""))
        webhook_report = report["webhook"]
        assert isinstance(webhook_report, dict)
        webhook_report.update({
            "actual_url": actual_url or None,
            "matches": bool(expected_url and actual_url == expected_url),
            "pending_update_count": int(webhook.get("pending_update_count", 0) or 0),
            "last_error": bool(webhook.get("last_error_message")),
        })
        if not actual_url:
            blockers.append("TELEGRAM_WEBHOOK_NOT_REGISTERED")
        elif expected_url and actual_url != expected_url:
            blockers.append("TELEGRAM_WEBHOOK_URL_MISMATCH")
        if webhook.get("last_error_message"):
            blockers.append("TELEGRAM_WEBHOOK_PROVIDER_ERROR")
    except TelegramProviderError as error:
        blockers.append(str(error).split(":", 1)[0])
    report["ok"] = bool(report["token_valid"]) and not blockers
    return report
