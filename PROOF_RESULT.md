# V-1.0 Proof Result — India 🟢-halal-only edge (2026-06-18)

Unified `RuleStrategy`, leakage-certified, run on the halal universe (85 tickers,
64 with data, 3y, **net of slippage + commission**), via `src/proof.py`.

## Headline: the entry signal adds real value — it clears the gate

| metric (NET of costs) | RuleStrategy (7-criteria) | Random-entry control (same exits) |
|---|---|---|
| Trades | 568 | 837 |
| Win rate % | 45.1 | 46.8 |
| Profit factor | **1.51** | **0.97** |
| Avg return / trade % | **+0.017** | **−0.001** |
| Sharpe (annualized*) | 2.08 | −0.16 |
| Total return % | **+10.2** | **−0.5** |

Random entries through the **same** 2:1 risk/exit engine are net-**losing**. The
7-criteria entry flips it net-**positive**. So the edge is in the signal, not just
the exit structure riding market drift.

## Reconciling the ~0 Rank IC
Rank IC (confidence vs next-day return) ≈ **−0.006** — the entry does NOT predict
next-day direction. But trades are held multi-day to a 2R target; the entry filters
for trend/momentum setups where that asymmetric exit pays off. Edge = entry-selection
× exit-structure, **not** 1-day forecasting. (This is also why qlib factors aimed at
next-day IC may not be the upgrade lever they look like.)

## Cost drag
Gross → Net: PF 1.78 → 1.51, return 14.3% → 10.2%. Costs ate ~29% of gross profit. Survives.

## Caveats — why this is "encouraging," not yet "bankable"
- **Survivorship / point-in-time halal**: today's halal list applied across 3y of
  survivors → overstates results.
- **Sharpe annualization** (`*`): per-trade returns annualized at 252 → the absolute
  Sharpe (2.08) is almost certainly overstated.
- **Regime**: ~3y of Indian equities is largely a bull run. Untested in drawdown/chop.
- **Same-bar exit proxy** in `backtest_with_risk` may be slightly optimistic.

## Verdict
Edge survives **costs** AND a **random-entry control** → clears the council's gate to
continue. Harden the survivorship + regime caveats before trusting the *magnitude*.

## Regime-robustness (the edge is real, but FAIR-WEATHER)
Strategy vs random control across non-bull windows (net of costs, **raw ungated signal**):

| window | strategy PF / ret% | random PF / ret% |
|---|---|---|
| full 7y (incl. 2020 crash, 2022 correction) | **1.58 / +18.3%** | 1.04 / +1.1% |
| 2021-06 → 2023-06 (chop + −18% correction) | 0.78 / **−6.4%** | 0.43 / −9.1% |

- The signal **beats random in every regime** → relative skill is real and regime-agnostic.
- BUT the absolute edge is **long-momentum**: profitable in up/recovery markets (3y +10%,
  7y +18%), **loss-making in chop/correction (−6.4%)** when ungated.
- ⇒ the scanner's **regime gate** (CRASH → no trades; TRENDING_DOWN → strict) is
  **load-bearing, not optional**. This proof is the raw *ungated* signal = worst case.
  Validating gated-vs-ungated in the stress window is the key follow-up.
- maxDD figures (~−8% over 7y) are NOT real portfolio drawdowns (each ticker is an
  independent book); ignore the absolute DD.

**Calibrated expectation:** a halal long-only momentum harvester — makes money when markets
trend up, must sit in cash (via the regime gate) during corrections.

## Survivorship quantification (this DOWNGRADES the verdict)
Buy-and-hold of the *current* halal universe = the pure survivor beta:

| window | B&H avg / median / %positive | RuleStrategy | Random ctrl |
|---|---|---|---|
| full 7y | **+337% / +169% / 100% positive** | +15% | −11% |
| 2021–2023 stress | +97% / +77% / 90% positive | −1.6% | −5.0% |

- **Survivorship is severe.** Over 7y, **100% of today's halal names were positive** (avg
  +337% buy-and-hold). The universe is composed entirely of survivors that thrived — a list
  including the failed/delisted names would not be 100% green. Every backtest on it is
  optimistically biased.
- **The strategy's edge is thin and survivorship-propped.** The random control **loses money
  even on a universe where every stock went up** — so the strategy's positive result leans
  heavily on the all-winner universe. On a realistic universe with failures, the +15% would
  likely erode toward/below zero.
- **Active badly trails passive.** Holding the halal universe returned ~+337% (7y); the active
  daily-signal machinery returned a small fraction of that, and **lost money in the stress
  window despite the universe averaging +97%.** The signals/stops/costs subtracted value vs
  simply holding. (Strategy total-return isn't a clean portfolio number, but the direction and
  magnitude are unambiguous.)

## Revised verdict
The earlier "positive, beats random + costs" result must be **downgraded**. The active edge is
**fragile, survivorship-propped, and dominated by buy-and-hold**. For a halal long-only investor,
the evidence points to **passive/rebalanced halal investing >> this active momentum signal**. The
durable value of this project is the **halal screening + risk/Zakat overlay**, not daily entry signals.

