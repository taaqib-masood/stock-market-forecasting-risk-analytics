"""
Telegram notifier — queues consent-bound recommendation cards for approved delivery.

Setup:
  1. Create a bot with @BotFather and configure TELEGRAM_TOKEN.
  2. Configure TELEGRAM_WEBHOOK_SECRET and an HTTPS TELEGRAM_WEBHOOK_URL ending
     in /telegram/webhook.
  3. Register the webhook and let each user opt in with /start terms-v1.
     The bot obtains each chat ID from Telegram; operators never provide a
     recipient list manually.

Then every morning at market open you get a message like:

  🎯 TOP TRADES — Mon 06 Apr

  #1 RELIANCE  Score: 85
  ━━━━━━━━━━━━━━━━━━━━━━━
  Entry  : ₹2,850.00
  Stop   : ₹2,784.30  (-2.3%)
  Target : ₹2,980.00  (+4.6%)
  R:R    : 2.5 : 1
  Shares : 7
  Invest : ₹19,950
  Risk   : ₹460  |  Reward: ₹1,150
  RSI    : 58.2  |  Vol surge: 1.8x
  ━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

from src.reliability.outbox import DeliveryOutbox
from src.reliability.telegram_audience import TelegramAudience
from src.telegram_provider import webhook_secret_is_valid


class DeliveryError(RuntimeError):
    """Telegram did not provide a valid acknowledgement."""


@dataclass(frozen=True)
class DeliveryAck:
    message_id: str
    provider: str = "telegram"


def acknowledge_shadow_payload(payload: str) -> DeliveryAck:
    """Acknowledge a shadow outbox row without contacting Telegram."""
    digest = hashlib.sha256(str(payload).encode("utf-8")).hexdigest()[:24]
    return DeliveryAck(message_id="shadow:" + digest, provider="shadow")


def _recommendation_delivery_approved() -> bool:
    """Return true only for an explicitly approved private/public release."""
    from src.reliability.controls import operational_kill_switch_active

    if operational_kill_switch_active():
        return False
    if os.environ.get("BORO_RELIABILITY_MODE", "research").lower() not in {"private", "public"}:
        return False
    try:
        from src.reliability.governance import (
            evaluate_release, load_policy, load_release_corporate_action_audit,
        )
        evidence = json.loads(Path(os.environ.get(
            "BORO_RELEASE_EVIDENCE", "data/reliability/current-release-evidence.json"
        )).read_text(encoding="utf-8"))
        policy = load_policy(Path(os.environ.get(
            "BORO_RELEASE_POLICY", "config/reliability-policy.json"
        )))
        return evaluate_release(
            evidence, policy,
            corporate_action_audit=load_release_corporate_action_audit(),
        ).get("approved") is True
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def send_raw(text: str, *, chat_id: str | None = None) -> DeliveryAck:
    """Send one Telegram message to an explicitly supplied recipient."""
    token = os.environ.get("TELEGRAM_TOKEN", "")
    target = str(chat_id or "").strip()
    if not token:
        raise DeliveryError("Telegram credentials are not configured")
    if not target:
        raise DeliveryError("Telegram recipient must be supplied by a consent-bound path")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": target,
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    request = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DeliveryError(f"Telegram request failed: {exc}") from exc
    message_id = body.get("result", {}).get("message_id") if body.get("ok") else None
    if message_id is None:
        raise DeliveryError(f"Telegram rejected message: {body.get('description', 'unknown error')}")
    return DeliveryAck(message_id=str(message_id))


def queue_recommendation_for_audience(
    text: str,
    signal_id: str,
    audience: TelegramAudience,
    outbox: DeliveryOutbox,
    *,
    now: str | datetime,
) -> dict[str, object]:
    """Queue one recommendation per active, explicitly-consented recipient."""
    if not _recommendation_delivery_approved():
        return {"queued": 0, "created": 0, "blockers": ["RELEASE_GATE_NOT_APPROVED"]}
    if not os.environ.get("TELEGRAM_TOKEN", "").strip():
        return {"queued": 0, "created": 0, "blockers": ["TELEGRAM_CREDENTIALS_MISSING"]}
    webhook_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not webhook_secret:
        return {"queued": 0, "created": 0, "blockers": ["TELEGRAM_WEBHOOK_SECRET_MISSING"]}
    if not webhook_secret_is_valid(webhook_secret):
        return {"queued": 0, "created": 0, "blockers": ["TELEGRAM_WEBHOOK_SECRET_INVALID"]}
    delivery_metrics = outbox.metrics()
    if int(delivery_metrics.get("dead_letter", 0)) or int(delivery_metrics.get("unreconciled", 0)):
        return {"queued": 0, "created": 0, "blockers": ["TELEGRAM_DELIVERY_HEALTH"]}
    current_terms = os.environ.get("BORO_TELEGRAM_TERMS_VERSION", "terms-v1").strip()
    all_recipients = audience.active_subscribers()
    recipients = audience.active_subscribers(current_terms)
    if all_recipients and not recipients:
        return {"queued": 0, "created": 0, "blockers": ["TELEGRAM_CONSENT_VERSION_OUTDATED"]}
    if not recipients:
        return {"queued": 0, "created": 0, "blockers": ["TELEGRAM_AUDIENCE_EMPTY"]}
    created = 0
    for recipient in recipients:
        chat_id = recipient["chat_id"]
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "consent_version": recipient["consent_version"],
            "consented_at": recipient["consented_at"],
        }, sort_keys=True)
        result = outbox.enqueue(
            audience.idempotency_key(signal_id, chat_id), signal_id, payload, now=now
        )
        created += int(result["created"])
    return {"queued": len(recipients), "created": created, "blockers": [],
            "consent_versions": sorted({r["consent_version"] for r in recipients})}


def send_outbox_payload(payload: str) -> DeliveryAck:
    """Deliver a recipient-bound outbox payload and preserve provider acknowledgement."""
    if not _recommendation_delivery_approved():
        raise DeliveryError("release approval is no longer active")
    webhook_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not webhook_secret:
        raise DeliveryError("Telegram webhook secret is not configured")
    if not webhook_secret_is_valid(webhook_secret):
        raise DeliveryError("Telegram webhook secret is invalid")
    try:
        value = json.loads(payload)
        chat_id = value["chat_id"]
        text = value["text"]
        consent_version = value["consent_version"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise DeliveryError("Telegram outbox payload is invalid") from error
    if not isinstance(chat_id, str) or not isinstance(text, str) or not isinstance(consent_version, str):
        raise DeliveryError("Telegram outbox payload fields are invalid")
    current_terms = os.environ.get("BORO_TELEGRAM_TERMS_VERSION", "terms-v1").strip()
    if consent_version != current_terms:
        raise DeliveryError("Telegram consent version is no longer current")
    database = os.environ.get("BORO_TELEGRAM_AUDIENCE_DB",
                              os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db"))
    with TelegramAudience(database) as audience:
        if not audience.consent_is_active(chat_id, consent_version):
            raise DeliveryError("Telegram consent is no longer active for this recipient")
    return send_raw(text, chat_id=chat_id)


def _send(text: str) -> bool:
    """Deprecated direct-send shim; never bypass consent or the outbox."""
    return False


def queue_audience_message(
    text: str,
    signal_id: str,
    *,
    now: str | datetime | None = None,
    database: str | None = None,
) -> dict[str, object]:
    """Queue and deliver a generic message through the consent-bound audience."""
    from src.reliability.store import ReliabilityStore

    point = now or datetime.now(timezone.utc)
    db_path = database or os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
    audience_db = os.environ.get("BORO_TELEGRAM_AUDIENCE_DB", db_path)
    with ReliabilityStore(db_path) as store:
        outbox = DeliveryOutbox(store.connection)
        if os.path.abspath(str(audience_db)) == os.path.abspath(str(db_path)):
            audience = TelegramAudience(store.connection)
            queued = queue_recommendation_for_audience(
                text, signal_id, audience, outbox, now=point
            )
            if not queued.get("queued"):
                return queued
            return {**queued, "delivery": outbox.deliver_due(send_outbox_payload, now=point)}
        with TelegramAudience(audience_db) as audience:
            queued = queue_recommendation_for_audience(
                text, signal_id, audience, outbox, now=point
            )
        if not queued.get("queued"):
            return queued
        return {**queued, "delivery": outbox.deliver_due(send_outbox_payload, now=point)}


def _card_text(i: int, card: dict) -> str:
    direction = "📈 BUY" if card["signal"] == "BUY" else "📉 SELL"
    stop_pct  = round((card["stop"]  / card["entry"] - 1) * 100, 2)
    tgt_pct   = round((card["target"]/ card["entry"] - 1) * 100, 2)
    return (
        f"<b>#{i} {card['ticker']}</b>  Score: {card['score']}/100\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Signal : {direction}\n"
        f"Entry  : ₹{card['entry']:,.2f}\n"
        f"Stop   : ₹{card['stop']:,.2f}  ({stop_pct:+.1f}%)\n"
        f"Target : ₹{card['target']:,.2f}  ({tgt_pct:+.1f}%)\n"
        f"R:R    : {card['rr']} : 1\n"
        f"Shares : {card['shares']}\n"
        f"Invest : ₹{card['invest']:,.0f}\n"
        f"Risk   : ₹{card['risk_rs']:,.0f}  |  Reward: ₹{card['reward_rs']:,.0f}\n"
        f"RSI    : {card['rsi']}  |  Vol surge: {card['vol_surge']}x\n"
        f"5d ret : {card['ret_5d']:+.2f}%\n"
    )


def send_trade_cards(
    cards: list[dict],
    date_str: str = "",
    *,
    signal_id: str | None = None,
    audience: TelegramAudience | None = None,
    outbox: DeliveryOutbox | None = None,
    now: str | datetime | None = None,
) -> bool:
    """Queue trade cards for explicitly-consented recipients.

    This legacy helper remains available to the CLI, but it must use the
    consent-bound audience registry and never a default chat ID.
    """
    if not _recommendation_delivery_approved():
        return False

    if audience is None or outbox is None or not str(signal_id or "").strip():
        return False

    if not cards:
        message = "🔍 No high-conviction trades today. Stay patient."
    else:
        header = f"🎯 <b>TOP TRADES — {date_str}</b>\n\n"
        body   = "\n".join(_card_text(i + 1, c) for i, c in enumerate(cards))
        footer = (
            "\n⚠️ <i>Place these on Zerodha as CNC (delivery) orders.\n"
            "Set GTT stop-loss immediately after entry.\n"
            "Never risk more than 2% of capital per trade.\n"
            "Educational information, not individualized financial advice. Send /stop to unsubscribe.</i>"
        )
        message = header + body + footer

    result = queue_recommendation_for_audience(
        message,
        str(signal_id).strip(),
        audience,
        outbox,
        now=now or datetime.now(timezone.utc),
    )
    return bool(result.get("queued")) and not result.get("blockers")


def send_journal_summary(summary: dict) -> bool:
    text = (
        "📊 <b>Trade journal updated</b>\n\n"
        "Review the authenticated cockpit for personal performance details."
    )
    import hashlib
    signal_id = "journal:" + hashlib.sha256(
        json.dumps(summary, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    result = queue_audience_message(text, signal_id)
    return bool(result.get("queued")) and not result.get("blockers")
