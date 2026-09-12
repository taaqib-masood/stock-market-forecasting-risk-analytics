"""Pure Telegram consent-command handling for the recommendation audience."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from src.reliability.telegram_audience import TelegramAudience, TelegramAudienceError


_COMMAND = re.compile(r"^/(start|stop|unsubscribe|revoke|help|status)(?:@[^\s]+)?(?:\s+(.*))?$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _chat_id(update: dict[str, Any]) -> str | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("id") is None:
        return None
    return str(chat["id"])


def handle_update(
    update: dict[str, Any],
    audience: TelegramAudience,
    *,
    consent_version: str,
    now: str | datetime | None = None,
) -> dict[str, Any]:
    """Process only explicit consent/revocation commands from Telegram updates."""
    chat_id = _chat_id(update)
    if chat_id is None:
        return {"handled": False, "reason": "CHAT_ID_MISSING"}
    message = update["message"]
    text = message.get("text")
    if not isinstance(text, str):
        return {"handled": False, "reason": "COMMAND_MISSING", "chat_id": chat_id}
    match = _COMMAND.fullmatch(text.strip())
    if match is None:
        return {"handled": False, "reason": "COMMAND_UNSUPPORTED", "chat_id": chat_id}

    command, argument = match.groups()
    point = now or _now()
    if command == "help":
        return {
            "handled": True,
            "action": "HELP",
            "chat_id": chat_id,
            "reply": (
                "Boro Telegram controls:\n"
                f"/start {consent_version} — subscribe to recommendations\n"
                "/status — check this chat's subscription\n"
                "/stop — revoke consent immediately"
            ),
        }
    if command == "status":
        active = audience.consent_is_active(chat_id, consent_version)
        return {
            "handled": True,
            "action": "STATUS",
            "chat_id": chat_id,
            "subscription_status": "ACTIVE" if active else "NOT_SUBSCRIBED",
            "reply": (
                "This chat is subscribed to Boro recommendations."
                if active
                else f"This chat is not subscribed. Send /start {consent_version} to opt in."
            ),
        }
    if command == "start":
        if str(argument or "").strip() != str(consent_version).strip():
            return {
                "handled": True,
                "action": "CONSENT_REQUIRED",
                "chat_id": chat_id,
                "reply": f"To opt in, send /start {consent_version}. You can leave anytime with /stop.",
            }
        try:
            subscription = audience.subscribe(
                chat_id, consent_version, now=point
            )
        except TelegramAudienceError as error:
            return {"handled": True, "action": "REJECTED", "chat_id": chat_id,
                    "reply": str(error)}
        return {
            "handled": True,
            "action": "SUBSCRIBED",
            "chat_id": chat_id,
            "subscription": subscription,
            "reply": "You are subscribed to Boro recommendations. Send /stop to revoke consent.",
        }

    revoked = audience.revoke(chat_id, now=point)
    return {
        "handled": True,
        "action": "REVOKED" if revoked else "ALREADY_REVOKED",
        "chat_id": chat_id,
        "reply": "Boro recommendations are disabled for this chat.",
    }
