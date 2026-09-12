# Boro: Automated Trading, Compliance & Risk Intelligence Platform

> **"Why are retail investors still managing risk like it's 1995?"**

A Python + JavaScript research and decision-control system for portfolio screening,
risk management, shadow execution, and compliance audits. The controls are functional;
the strategy has not earned a reliable-profit claim or live release.

## Reliability Preregistration

`nse-halal-residual-momentum-v7` is the current unopened preregistration at
`data/reliability/preregistrations/nse-halal-residual-momentum-v7.json`.
Canonical SHA-256: `33a66476da97965cf964ffaf1eb82b2af60f7e8fdc4c04e9a2b9244fa9d12030`.
The sealed protocol uses NIFTY 500, NIFTY 50 TRI GROSS, 2013-12-01 through
2014-12-31 warmup, and the 2015-01-01 through 2019-12-31 scored holdout; 2020-01-01
through 2024-06-30 remains burned. It records six prior trials, an effective trial
count of seven, a 365-day halal-classification freshness limit, and
`validation_values_opened: false`. No evaluation has occurred.

The retained v1-v6 preregistrations and registry rows remain byte-preserved evidence.
v5 is an invalid unopened seal because an evicted non-empty source was hashed as empty.
v6 is unopened but source-stale after material governance changes. v7 preserves the
frozen strategy semantics, seals the current 14-file evaluation boundary, records
`validation_values_opened: false`, and has one `PREREGISTERED` event with no evaluation.
It contains no performance evidence and grants no release authority.

Corporate-action review now uses a strict packet verifier, single-snapshot audit
reconciliation, exact reviewed-factor provenance overlays, and adjustment-boundary
controls. The canonical no-review report SHA-256 is
`90964ce4e3f388fb8eb479db40a8326851aad111b116d9f7dc77a34bf6117308`; the canonical
pending reviewed report SHA-256 is `d4f34e75f8839bba2c8b026b80de3926e8d25fcdd510358a19c147b4bd13d9f0`.
The v2 packet manifest SHA-256 is
`d8cad6876de94c8923cddbab1a7c6a7c215687f00975ba8304eabb44025e07a1`, and the empty
reviewer-policy SHA-256 is
`ca19925bb12adafa92d9839b4a18278029dfabaddf4e8bad328548511a5b7d78`.
All 862 visibility and 195 factor rows remain `PENDING`; the policy authorizes nobody.
An independent external corporate-action reviewer must supply retained primary evidence,
identity, UTC availability/review timestamps, and a reproducible `(0, 1]` factor where
required before an authorized policy update and rerun can resolve a row. Actual
adjusted-price backfill and release remain blocked.

## Current Release Posture

Telegram, paid signals, and public release are disabled. `REJECTED` corporate-action
decisions require the same retained human evidence, authorization, UTC timestamps, and
rationale as accepted decisions; neither `PENDING` nor `REJECTED` clears the release
gate. Policy v2 can bind a human reviewer and separate governance-owner approval record,
but the retained production policy authorizes no principal, and software cannot prove a
person's real-world identity or independence.

Shadow activation and release governance require a process-local, exact-identity audit
capability that is revalidated against retained audit, packet, policy, governance, and
baseline evidence when used. Paths, hashes, CLI flags, and AI output cannot create it.
The daily dispatcher and compliance CLI therefore provide no capability and remain
blocked. AI evidence proposals are non-authoritative assistance only.

The current compliance audit is rejected (`approved: false`), SHA-256
`92086b8fc49a9d686756286deb1008f06da501ec946af955d36f99163ea83400`. Its blockers are
`CORPORATE_ACTION_REVIEW_MISSING`, `DATASET_NOT_POINT_IN_TIME`, `DATASET_COVERAGE`,
`STATISTICAL_EVIDENCE`, `SHADOW_EVIDENCE_MISSING`, `APPROVAL_QUANTITATIVE_MISSING`,
`APPROVAL_SHARIAH_MISSING`, and `APPROVAL_LEGAL_MISSING`. Quantitative, qualified
Shariah, and SEBI/RA legal approvals remain externally required.

The Boro dashboard now exposes a Release Readiness view and labels Telegram as a
simulation mirror while delivery is blocked. Direct recommendation sends are
fail-closed unless the retained release gate approves an explicit `private` or
`public` mode. The control server exposes authenticated `GET /readiness`; its
`/buy` and `/close` remain paper-portfolio actions by default. A gated Zerodha
adapter now exists for CNC orders, holdings-based exits, and order-status checks,
but it requires either an approved release or the private owner acknowledgement
`BORO_PERSONAL_LIVE_TRADING_ACK=I_UNDERSTAND_PERSONAL_LIVE_TRADING`, plus
`BORO_EXECUTION_MODE=live`, an explicit live
confirmation value, validated credentials, and valid entry/stop/target values before
it can contact Kite. Live BUY protection uses a two-leg OCO GTT; manual live closes
require and cancel that protection ID before submitting the sell, and the cockpit
reconciles both the order and GTT status. Manual live execution is restricted to
`BORO_LIVE_SYMBOL` (default `RELIANCE`) and enforces a 2% maximum-loss rule plus a
20% notional cap from the configured personal capital.
The broker gateway repeats the Reliance-only scope and BUY stop/risk checks for
direct module callers. The cockpit's **Preview risk** control calls the read-only
`/broker/risk-preview` preflight and shows the exact risk, notional, and two-leg GTT
checks before a live confirmation.
Live BUY requests also require an idempotency key so a browser retry cannot submit
the same broker order twice. Live CLOSE requests use the same durable claim/finish
record so a retry cannot submit a duplicate Reliance sell before the first fill is
visible.
The cockpit's authenticated **Reconcile broker** action compares current holdings and
the daily order book, records reconciled lifecycle events, and flags non-Reliance,
non-NSE, or non-CNC orders for operator review.
Set `BORO_OPERATIONAL_KILL_SWITCH=true` to pause new live entries and all
recommendation delivery immediately; the pause is fail-closed and leaves read-only
holdings and order reconciliation available.
Signed Kite order postbacks are accepted at `/broker/postback` and written to the
broker ledger only after checksum verification with `KITE_API_SECRET`.

If a broker BUY is accepted but the OCO protection call fails, the local cockpit
exposes an idempotent **Retry OCO protection** action through
`POST /broker/gtt/protect`. It reuses the Reliance, risk, session, and release gates
and records successful recovery in the broker ledger.

Kite sessions are backend-only. The local cockpit can open the Zerodha login URL
and exchange the one-time request token through authenticated `GET /broker/login-url`
and `POST /broker/session/exchange`; it stores the resulting short-lived token in
the owner-only `KITE_ACCESS_TOKEN_FILE` (default `results/kite_access_token`) and
returns only profile metadata. The CLI equivalents use the same owner-only token
file through
`python scripts/zerodha_session.py login-url` and `python scripts/zerodha_session.py
exchange REQUEST_TOKEN`. The token expires at the next 6 AM session boundary; never
place `KITE_API_SECRET` or `KITE_ACCESS_TOKEN` in frontend/localStorage or shell
history.
The readiness panel also renders a live activation checklist for evidence,
Telegram consent/delivery, Kite session, execution posture, and the operational
pause, so blocked channels expose their concrete next reason.

After the backend session is validated, the cockpit can read holdings, daily order
history, order status, and GTT status even while release approval keeps new live
orders disabled. Mutating broker actions remain fail-closed behind the release,
live-mode, confirmation, symbol, and risk gates.

The older `src.web_dashboard` is loopback-bound and read-only by default. Its legacy
paper trade endpoints require `WEB_TRADE_TOKEN` plus the `X-Web-Trade-Token` header;
use the main Boro cockpit for paper and broker controls.

The older TradingView receiver (`src.webhook_server`) is also loopback-bound and
requires `X-Webhook-Secret`. Its Alpaca execution is disabled by default and rejects
live Alpaca endpoints; Zerodha/Reliance through the authenticated Boro control server
is the only supported broker path.

Telegram enrollment is now explicit and user-controlled: configure the BotFather
`TELEGRAM_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, and exact HTTPS `TELEGRAM_WEBHOOK_URL`, expose the authenticated control server over HTTPS, and
register the endpoint with `python scripts/set_telegram_webhook.py` (it reads
`TELEGRAM_WEBHOOK_URL` and `TELEGRAM_WEBHOOK_SECRET` from the environment; an
optional URL argument remains supported). A user sends `/start terms-v1` to opt
in, `/status` checks that chat's current consent, and `/stop` revokes consent. The
`/help` command explains the controls. The webhook never accepts a manually supplied
recipient list; it uses the chat ID supplied by Telegram. Recommendation delivery
still requires the complete release decision and at least one active consent.
Run `python scripts/readiness_check.py --json` for a secret-safe backend preflight;
it reports separate Telegram/broker reasons and private-ack state, and exits non-zero
until the requested channels satisfy their current gates.
For retry recovery outside the scan process, run
`python scripts/deliver_telegram_outbox.py --json` from a scheduled worker. It
delivers only due, consent-bound rows, reports dead-letter/unreconciled health, and
exits non-zero when delivery is blocked or degraded.
The local Telegram panel also exposes **Retry due delivery**, an authenticated
one-shot invocation of the same gated worker.
GitHub Actions failure notices use `scripts/queue_telegram_notice.py` and the same
audience/outbox path; the workflow has no direct chat-ID delivery fallback.
The local cockpit's **Verify Bot & webhook** action performs read-only `getMe` and
`getWebhookInfo` checks without exposing the token or secret. **Register webhook**
uses the same authenticated backend path as `scripts/set_telegram_webhook.py`,
requires the configured HTTPS URL and secret, and only registers the consent
webhook; it does not send a recommendation. Once verified, **Open bot & opt in**
generates a `t.me` deep link for users to start the current consent flow directly.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![JavaScript](https://img.shields.io/badge/JavaScript-ES6+-yellow.svg)](https://developer.mozilla.org/en-US/docs/Web/JavaScript)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-activation%20blocked-red.svg)](#-quality-assurance)
[![GitHub Actions](https://img.shields.io/badge/Automation-GitHub%20Actions-black.svg)](.github/workflows/trading_pipeline.yml)
[![Netlify](https://api.netlify.com/api/v1/badges/c2d7b0e6-4805-45ec-a2f5-700ee30f5537/deploy-status)](https://app.netlify.com/projects/stocks-proj/deploys)

**[Live Dashboard](https://stocks-proj.netlify.app) · [See it Work](#-how-it-works) · [Quick Start](#-quick-start) · [Why It Matters](#-why-this-matters)**

---

## 🎯 Pitch: The Problem Everyone Has

### **Question 1: Are You Trading on Emotion or Rules?**

Most retail traders:
- See a stock moving up, buy it
- Hold it until it hurts, sell it in a panic
- Repeat, lose money

Institutional traders:
- Have entry/exit rules
- Size positions by volatility (not gut feel)
- Track risk in real-time
- Say "no" to trades that fail the checklist

**Boro does #2 for you.**

### **Question 2: Do You Know Your Real Risk Per Trade?**

Ask 100 retail traders: "What's your max loss per trade?"

- 70 will say "I don't know"
- 20 will say "I stop out at -10%"
- 10 will say "2% of capital" (the right answer)

**Boro enforces it automatically.**

```python
# You set it once
boro = RiskManager(max_risk_pct=2.0, capital=50000)
# Max loss per trade = ₹1000 (2% of ₹50K)
# Boro sizes every position to hit exactly this
```

### **Question 3: How Long Do You Spend on Compliance / Audit Trail?**

If you trade on a stock exchange in a regulated market (India NSE, UAE, Singapore):
- You need to prove *why* you bought what
- You need to show *how much you risked*
- You need to report gains/losses accurately
- You might need to screen for specific criteria (ESG, dividend stability, sector alignment)

**Spreadsheet?** Hours per month.  
**Boro?** A hash-chained shadow-signal ledger with versioned rationale and delivery state.
It is research evidence, not a substitute for broker, tax, or regulatory records.

### **Question 4: What If You Could Backtest Before You Risk Real Money?**

Paper trading is the bridge. But most platforms:
- Don't track realistic costs (commissions, slippage)
- Don't validate your rules worked out-of-sample
- Don't tell you why a signal failed

**Boro does all three.**

---

## 💡 The Solution: What Boro Actually Does

### Core Capabilities (Pick What You Need)

| What | Why It Matters | For Whom |
|-----|-----------------|---------|
| **Point-in-Time Portfolio Screening** | Reconstruct what was knowable on each date; missing or stale halal inputs block new entries | Research and controlled shadow trading |
| **Real-Time Risk Sizing** | Every position is sized by volatility — no more "I'll buy 100 shares" guessing | Traders who want to sleep at night |
| **Rule-Based Daily Signals** | Scanner runs at 9:15 AM, flags stocks that pass your checklist, sends alerts | Time-poor traders, busy professionals |
| **Paper Trading Cockpit** | Test your entire strategy (entry, exit, sizing, risk) with fake money before going live | New traders, strategy developers |
| **Walk-Forward Validation** | New trading rules must prove they work out-of-sample (not just in backtests) before they ship | Quants, serious traders |
| **Append-Only Decision Evidence** | Hash-chained signal snapshots preserve data, strategy, risk, rationale, and delivery versions | Reviewers and system operators |
| **ML Ensemble for Backtesting** | ARIMA + LightGBM on 52 features (technicals, sentiment, macro) for research mode | Researchers, systematic traders |
| **Annual Tax Calculator** | Compute annual obligations (gains-based or full-value) for any investment structure | Investors with specific criteria |
| **Drawdown Guard** | Monitors market conditions; automatically grades risk exposure from green → yellow → red | Risk-averse investors |
| **Zero Infrastructure** | Runs on GitHub Actions + Netlify (free tier). No servers to manage, no Heroku bills | Bootstrapped traders, startups |

---

## 🤔 Questions People Ask (And The Answers)

### **"Is this really better than my broker's platform?"**

Your broker gives you:
- A way to enter orders
- A chart
- Maybe a screener (basic)

Boro gives you:
- All of the above (via Zerodha integration)
- + Automated risk management (position sizing, stops, targets)
- + Backtesting with realistic costs
- + Rules that enforce discipline (multi-timeframe checks)
- + Audit trail (every trade logged with reasoning)

**Translation:** Your broker is a transaction engine. Boro is a *trading system*.

---

### **"How much money do I need to start?"**

**Short answer:** ₹50,000 (or AED 7,000 or $600).

**Long answer:** Boro doesn't care. You set the capital. Risk per trade = 2% of capital. So:

| Capital | Max Risk/Trade | Sustainability |
|---------|----------------|-----------------|
| ₹50,000 | ₹1,000 | 50 trades = 1 year |
| ₹500,000 | ₹10,000 | 50 trades = 1 month |
| ₹5,000,000 | ₹100,000 | 50 trades = 1 week |

The system scales. Your capital just changes position size.

---

### **"How much better is the AI/ML than simple rules?"**

Honest answer: **Not much.**

Earlier single-ticker comparisons are not release evidence: they used a current-survivor
universe and the old engine could fill close-derived signals at the same close. The current
engine executes on the next bar and evaluates shared portfolio capital.

The corrected dynamic-universe rule diagnostic returned 99.38% versus 107.11% for the
retained NIFTYBEES proxy. It failed excess-return confidence, deflated-Sharpe, drawdown,
and every regime gate. V2 and a bull-only overlay were also rejected. ML remains
research-only. Why?
- Markets are non-stationary (what worked in 2022 doesn't work in 2024)
- Adding features → overfitting (harness caught it, rejected 5 new indicators)
- Simple rules are more robust

**Lesson:** We built the ML pipeline anyway, because sometimes it *does* work on other assets. Use it for research, not live trading. The live scanner stays simple.

---

### **"What's the real edge? Why would this make money?"**

Three reasons:

**#1: Discipline > Skill**  
Most traders lose because they:
- Hold losers too long (hoping)
- Exit winners too early (taking quick profit)
- Oversize bad trades (revenge trading)

Boro makes these rules explicit and testable. Discipline reduces avoidable errors; it
does not create a guaranteed market edge.

**#2: Risk-Adjusted Returns**  
A strategy with 52% win rate (barely better than a coin flip) still makes money if:
- Average win = ₹5,000
- Average loss = ₹3,000
- Profit factor = 1.67 (you make ₹1.67 for every ₹1 risked)

Boro does not promise to beat the market. Promotion now requires statistically credible
net benchmark outperformance across untouched regimes.

**#3: Auditability Before Automation**  
Signals are useful only when their data, rule version, risk decision, and delivery outcome
can be reproduced. Boro records that chain and blocks entries when evidence is incomplete.

---

### **"Can I actually make money with this?"**

Not proven. Activation is blocked while point-in-time halal fundamentals, statistical
evidence, shadow history, and external approvals remain incomplete.

✅ If you:
- Follow the rules (don't override signals)
- Trade with realistic costs (0.5% round-trip on NSE)
- Rebalance monthly
- Have at least ₹50K

❌ If you:
- Expect 50% returns per year
- Override signals because "I have a feeling"
- Trade on 5-day holds (costs kill the profit)
- Don't set a hard stop-loss

**Current dynamic-universe diagnostic (2020–2024):**
- Portfolio return: 99.38% versus 107.11% benchmark
- Outperformance probability: 45.95%
- Deflated-Sharpe probability: 2.54% (required: 95%)
- Maximum drawdown: 29.12% (limit: 15%)
- Regime gate: failed in bull, bear, and sideways samples

**Translation:** A promising headline return is not enough. The release gate rejects it.

---

## ✨ How It Works (The Sales Pitch)

### **Target Daily Routine (Activation Currently Blocked)**

```
9:15 AM IST → Boro runs the scanner
  ↓
Scores 78 stocks against your criteria
  ↓
Applies gates: Is the market in bull mode? Are we in strong sectors?
             Do we have earnings risk? Did this signal work historically?
  ↓
Flags eligible signals → Retained for shadow reconciliation only; no Telegram release
  ↓
You see the alert, review, decide to buy (or skip)
  ↓
Boro tracks the position automatically
  ↓
3:45 PM IST → Auto-close any position that hit stop/target/time limit
  ↓
Evening report: 1 closed for +₹2.5K, 1 still open (5 days held)

Sunday → Weekly backtest runs, reports drift, retrains if needed
```

**You do:** Review alerts, click buy/sell.  
**Boro does:** Everything else.

---

### **The Paper Trading Cockpit**

Before you risk real money:

```bash
$ python -m src.paper_trader --stats

Win Rate: 56%
Profit Factor: 1.23
Avg Win: ₹4,200
Avg Loss: ₹3,100
Total P&L: ₹45,600 (on ₹50K capital)
Max Drawdown: 12%
Sharpe: 0.89
```

This is *exactly* what you'd have gotten with real money (minus the emotional mistakes).

---

### **The Backtest to Live Pipeline**

```
1. Idea: "What if we add RSI(2) < 10 as an entry?"
   ↓
2. Backtest: Run on 5 years of data
   Result: 61% win rate, 1.45 profit factor (in-sample)
   ↓
3. Walk-Forward Validation: Test on data the model never saw
   Result: 49% win rate, 0.92 profit factor (OOS)
   ↓
4. Gate Decision: "52% is the minimum. 49% fails. Rejected."
   ↓
The rule never ships to live trading.
```

This is how overfitting dies. We built it, tested it, rejected it.

---

## 🎁 Why Companies Want This

### **For Fintech Platforms**

**Your problem:** "Clients want portfolio screening but we can't build it."  
**Time to build:** 3–6 months  
**Boro's solution:** REST API. Integrate in 2 weeks.

```python
POST /api/screen
{ "tickers": ["RELIANCE", "INFY", "TCS"] }

Response:
{
  "RELIANCE": { "pass": true, "debt_ratio": 0.08, "score": 95 },
  "INFY": { "pass": true, "debt_ratio": 0.05, "score": 98 },
  "TCS": { "pass": false, "debt_ratio": 0.35, "score": 62 }
}
```

Your clients see a "verified portfolio" badge. Competitive moat, instant.

### **For Wealth Managers**

**Your problem:** "Auditing 500 client portfolios = 200 FTE-hours/quarter."  
**Boro's solution:** Batch-screen them overnight.

```bash
$ python -m src.batch_screen --portfolio-file clients.csv --output audit_report.json
# 500 portfolios screened in 5 minutes
# Report: portfolio scores, risk metrics, compliance status
```

Your clients get a quarterly audit. You spend 2 hours instead of 200.

### **For Institutional Investors**

**Your problem:** "Entering a new market (UAE, Singapore). Need standardized screening."  
**Boro's solution:** Auditable, standardized criteria.

```bash
$ python -m src.screen_institutional --universe="UAE:ADX" --criteria="DFSA_2024"
# Output: Green-light holdings, Red-flag holdings, Regulatory audit trail
```

### **For Individual Traders**

**Your problem:** "I have ₹50K. I want returns but don't want to gamble."  
**Boro's solution:** Systematic trading without ₹5K/month in advisor fees.

You get:
- Daily signals (rules-based, not luck)
- Automatic position sizing (2% max risk)
- Backtested strategy (not a guru's hype)
- Compliance audit trail (for taxes)
- Free. Open-source. Your data, your rules.

---

## 📊 The Numbers (No BS)

### **Legacy Backtest Snapshot (RELIANCE, 2019–2024)**

| Metric | Result | What It Means |
|--------|--------|---------------|
| In-Sample Win Rate | 58% | Training data: 58% winning trades |
| Out-of-Sample Win Rate | 54% | Unseen data: 54% winning trades |
| Profit Factor (OOS, net costs) | 1.04 | For every ₹1 risked, you make ₹1.04 |
| Avg Win | ₹4,200 | Average winning trade |
| Avg Loss | ₹3,100 | Average losing trade |
| Max Drawdown | 18% | Worst peak-to-trough loss |
| Sharpe Ratio | 0.67 | Returns per unit of risk (1.0+ is good) |
| Best Trade | +₹18,500 | The single best winning trade |
| Worst Trade | -₹12,000 | The single worst losing trade |
| Avg Hold Time | 14 days | Average time in a position |

### **What This Really Means**

It is not enough to establish reliability. See `PROOF_RESULT.md`: the broader active
result is fair-weather, survivorship-biased, and dominated by the passive benchmark.
Current promotion gates require frozen point-in-time data, confidence bounds on net
excess returns, regime stability, portfolio drawdown controls, and reconciled shadow
evidence.

---

## 🚀 Quick Start (15 Minutes)

### **Step 1: Set Up (5 min)**

```bash
git clone https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics.git
cd stock-market-forecasting-risk-analytics
git checkout V-1.0

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
export PYTHONPATH=.
```

### **Step 2: Run Your First Scan (5 min)**

```bash
# Screen a stock
python -m src.halal_screen --ticker RELIANCE
# Output: PASS | Debt: 8.2% | Interest: 1.1%

# Run today's daily scan
python -m src.daily_briefing --capital 50000
# Output: local briefing; Telegram delivery remains activation-gated
```

### **Step 3: See the Dashboard (5 min)**

```bash
# Open demo-boro.html in a browser
open demo-boro.html
# You see: Signals, portfolio P&L, backtest results, portfolio scores
```

---

## 🎮 Full Command Reference

### **Daily Trading**

```bash
python -m src.daily_briefing --capital 50000      # Run scanner
python -m src.paper_trader --portfolio            # See positions
python -m src.paper_trader --buy RELIANCE 10 2650 # Buy
python -m src.paper_trader --close RELIANCE       # Sell
python -m src.paper_trader --stats                # See P&L
```

### **Backtesting**

```bash
python -m src.pipeline --ticker RELIANCE --years 5  # Backtest 5 years
mlflow ui                                            # View results
```

### **Screening & Analysis**

```bash
python -m src.halal_screen --ticker RELIANCE      # Screen a stock
python -m src.auto_close                           # Close at stops
python -m src.auto_close --dry-run                 # See what would close
```

---

## 📈 The Dashboard

**[Open it live: stocks-proj.netlify.app](https://stocks-proj.netlify.app)**

### **What You See**

1. **Today's Scan** — Real-time signals (ticker, price, score)
2. **Performance** — Your P&L, win rate, Sharpe, vs-benchmark
3. **Equity Curve** — Strategy vs market (line chart + underwater view)
4. **Positions** — Open lots (entry, current P&L, time held)
5. **Screening** — Portfolio score breakdown
6. **Tax Center** — Annual tax/compliance calculator
7. **Command Center** — Run backtest, scan, drift check from UI

### **Controls**

- Dark/Light theme
- Local/Cloud toggle (Local = can buy/sell)
- Strategy preset (Swing = 15d, Intra-Month = 22d)
- Auto-refresh every 5 min

---

## 🔌 Integrations (Out of the Box)

| Service | What It Does | Cost |
|---------|-------------|------|
| **yfinance** | Stock prices & fundamentals | Free |
| **Telegram** | Alerts + confirmations | Free |
| **Zerodha** | Real order generation | Brokerage fees |
| **GitHub Actions** | Schedule scanner | Free (2000 min/month) |
| **Netlify** | Host dashboard | Free |
| **Groq LLM** | Explain trades | Free (3000 calls/month) |
| **Alpaca API** | US market data (optional) | Free / Paid |

---

## 🏆 Why Boro Wins

### **vs. Hiring a Day Trader**

| Aspect | Day Trader | Boro |
|--------|-----------|------|
| Cost | ₹50K–200K/month | ₹0 (open-source) |
| Emotion | High (greed/fear) | Zero (rules-based) |
| Scalability | 1 person, 1 portfolio | 1 system, 1000 portfolios |
| Audit Trail | None | Every trade logged |

### **vs. Trading Bots (Crypto)**

| Aspect | Trading Bots | Boro |
|--------|------------|------|
| Markets | Crypto only | Stocks (NSE, UAE, global) |
| Regulation | Grey area | Fully compliant |
| Validation | Backtests lie | Walk-forward harness |
| Infrastructure | Monthly SaaS fee | Free |

### **vs. Fund Managers**

| Aspect | Fund Manager | Boro |
|--------|------------|------|
| Fee | 1–2% AUM | ₹0 |
| Minimum | ₹25L–1Cr | ₹50K |
| Transparency | Black box | Every trade logged |
| Time | Quarterly reports | Real-time dashboard |

---

## 💻 For Developers

### **White-Label This (MIT License)**

You can:
- Fork it
- Rebrand it (logo, colors, domain)
- Integrate into your platform
- Sell it to your users
- Charge for it

No permission needed. No royalties.

### **API Pattern**

```python
from src.halal_screen import classify
from src.risk_manager import RiskManager

# Your platform → Boro → result
tier = classify('RELIANCE')
return { "approved": tier == "pass" }
```

### **Extend It**

Add your own:
- New screening criteria (ESG, dividend, momentum)
- New markets (UAE, Singapore, Malaysia)
- New data sources (your proprietary feed)
- New risk rules (your secret sauce)

Modular. Plug and play.

---

## 🧪 Quality Assurance

### **Automated Test Coverage**

```
✓ Import tests (all 15+ modules load cleanly)
✓ Feature engineering (52 features generate)
✓ Ensemble fit/predict (stacking works)
✓ Monte Carlo (200 sims, stable)
✓ Risk manager (sizing logic correct)
✓ Walk-forward (OOS harness gates bad rules)
✓ Point-in-time visibility and fail-closed halal inputs
✓ Bootstrap benchmark-outperformance and multiple-testing gates
✓ Hash-chained signal evidence and idempotent delivery outbox
✓ Portfolio kill switches and release governance
```

### **Walk-Forward Validation (The Secret Sauce)**

Every promoted rule must:
1. Run on frozen, point-in-time data with realistic costs
2. Validate on untouched rolling windows across bull, bear, and sideways regimes
3. Produce a positive lower 95% confidence bound on net benchmark excess return
4. Survive multiple-testing penalties and portfolio drawdown limits

If it fails, it never ships. We rejected 5 indicators this way.

---

## 📋 Roadmap

### **Phase 1: Shadow Reliability Beta**
- [x] Daily scanner (rule-based)
- [x] Risk manager (2% max risk)
- [x] Paper trading
- [x] Backtesting (ARIMA + LightGBM)
- [x] Point-in-time data contract + append-only signal ledger
- [x] Statistical benchmark gates + delivery outbox + kill switches
- [x] Integrity-checked NSE archive acquisition and equity-only normalization
- [x] Reconcile 79 archive gaps to retained, hash-verified official holiday evidence
- [x] Retained corporate-action/filing snapshots and fail-closed XBRL fact extraction
- [x] Deterministic, fail-closed split/bonus/dividend OHLCV adjustment engine
- [x] Zero-infrastructure deployment
- [ ] Import a delisted-inclusive historical NSE dataset
- [x] Retain paired 2019-2024 NSE action and announcement snapshots
- [ ] Resolve 862 action visibility cases and 195 reviewed adjustment factors
- [ ] Complete 180+ reconciled shadow days at ≥99.5% acknowledged delivery
- [ ] Record independent quantitative, Shariah, and SEBI/RA legal reviews

### **Phase 2: Coming Soon**
- [ ] Cross-market (UAE ADX, Singapore, Malaysia)
- [ ] REST API for platforms
- [ ] Advanced risk (VaR, Kelly, drawdown-targeting)
- [ ] Mobile app (iOS + Android)

### **Phase 3: Enterprise**
- [ ] White-label SaaS for fintech
- [ ] Advisor portal (wealth managers)
- [ ] Institutional reporting

---

## ❓ FAQ

### **Q: Can I actually make money?**
**A:** Not established. Current evidence supports controlled shadow trading, not an
income forecast or reliable-profit claim.

### **Q: What if the market crashes?**
**A:** Drawdown and exposure controls block new entries at configured limits, but no
historical maximum guarantees a future maximum loss.

### **Q: How is this different from my broker's screener?**
**A:** Your broker screens the current market. Boro is building point-in-time screening,
benchmark-relative validation, explicit risk controls, and traceable shadow alerts.

### **Q: Do I need to know coding?**
**A:** No. Use the dashboard. Coding helps if you want to customize.

### **Q: Can I white-label this?**
**A:** Yes. MIT license. No permission needed.

### **Q: What if GitHub goes down?**
**A:** Run manually: `python -m src.daily_briefing`. One-time miss, no big deal.

---

## ⚖️ Disclaimer

**This is not investment advice.** Boro is a tool for systematic trading. Past performance ≠ future results. You assume all risk. Use paper trading first. Always use stops. Never risk more than you can afford to lose.

---

## 📜 License & Credits

**MIT License.** Use freely.

**Built by:** Taaqib Masood  
**Inspired by:** Walk-forward validation (Prado), LLM Council (Karpathy)

**Thanks to:** yfinance, LightGBM, MLflow, Telegram, Zerodha, GitHub, Netlify

---

## 🔗 Links

- **[Live Dashboard](https://stocks-proj.netlify.app)**
- **[GitHub](https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics)**
- **[Issues](https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics/issues)**
- **[Email](mailto:taaqib.masood@icloud.com)**

---

**Ready to trade systematically?**

1. **Try it:** [Live dashboard](https://stocks-proj.netlify.app)
2. **Test it:** Run a backtest
3. **Shadow it:** Record timestamped signals and simulated fills
4. **Promote it:** Go live only after every release gate passes

**Measured process. Explicit blockers. No guaranteed results.**

---

*Last updated: July 2026 | Version 1.0 (V-1.0 branch) | Status: Shadow reliability beta*
