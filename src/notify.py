"""
Telegram notifier — sends daily trade cards to your phone.

Setup (free, 2 minutes):
  1. Open Telegram → search @BotFather → /newbot → copy token
  2. Search @userinfobot → get your chat_id
  3. Add to .env:
       TELEGRAM_TOKEN=xxxxxxxxxx:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
       TELEGRAM_CHAT_ID=123456789

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
from urllib.request import urlopen, Request
from urllib.error import URLError


def _send(text: str) -> bool:
    token   = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False

    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "HTML",
    }).encode()
    req = Request(url, data=payload,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10):
            return True
    except URLError:
        return False


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


def send_trade_cards(cards: list[dict], date_str: str = "") -> bool:
    if not cards:
        return _send("🔍 No high-conviction trades today. Stay patient.")

    header = f"🎯 <b>TOP TRADES — {date_str}</b>\n\n"
    body   = "\n".join(_card_text(i + 1, c) for i, c in enumerate(cards))
    footer = (
        "\n⚠️ <i>Place these on Zerodha as CNC (delivery) orders.\n"
        "Set GTT stop-loss immediately after entry.\n"
        "Never risk more than 2% of capital per trade.</i>"
    )
    return _send(header + body + footer)


def send_journal_summary(summary: dict) -> bool:
    if summary.get("trades", 0) == 0:
        return _send("📒 No closed trades yet.")

    text = (
        f"📊 <b>Trade Journal Summary</b>\n\n"
        f"Total trades  : {summary['trades']}\n"
        f"Open          : {summary.get('open', 0)}\n"
        f"Win Rate      : {summary['win_rate']}%\n"
        f"Profit Factor : {summary['profit_factor']}\n"
        f"Total P&L     : ₹{summary['total_pnl']:+,.2f}\n"
        f"Avg Win       : ₹{summary['avg_win']:+,.2f}\n"
        f"Avg Loss      : ₹{summary['avg_loss']:+,.2f}\n"
        f"Best trade    : ₹{summary['best_trade']:+,.2f}\n"
        f"Worst trade   : ₹{summary['worst_trade']:+,.2f}\n"
    )
    return _send(text)
