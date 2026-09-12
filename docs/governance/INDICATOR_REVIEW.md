# Daily-Bar Indicator Review

**Reviewed:** 2026-07-11  
**Decision:** Keep `RuleStrategy` V1 live; do not promote V2 or relative-strength selection.

## Architecture Findings

The production scanner does not trade directly from `scanner._score`. `_scan_one`
calls `backtest_runner.generate_live_signal` with `RuleStrategy`, the same strategy
used by the unified backtest engine. The old `_score` remains reachable through
`engine.alpha` and should be treated as legacy, not the production signal source.

`RuleStrategyV2` already implements the proposed daily-bar additions: ADX gating,
Donchian-20 breakout, Bollinger squeeze percentile, and volume z-score confirmation.
Relative-strength selection is implemented in the walk-forward harness, although it
is not part of live Telegram selection. The ML feature pipeline is a separate research
consumer and does not determine live signals.

## Exploratory Evidence

Five-year yfinance walk-forward smoke tests rejected V2:

- RELIANCE: 1 OOS trade, PF 0.00, net P&L -249.24.
- TCS: 4 OOS trades, PF 0.35, net P&L -534.69.

Three-year selection-aware testing covered 84 current names:

| Selection | Trades | Win rate | PF | Net P&L |
|---|---:|---:|---:|---:|
| Base | 773 | 32.3% | 0.83 | -22007.72 |
| Regime | 681 | 31.9% | 0.81 | -21242.49 |
| Relative strength | 628 | 31.7% | 0.80 | -20536.89 |
| Regime + RS | 527 | 30.9% | 0.73 | -22280.26 |

These results are survivorship-biased diagnostics, not production proof. They are
still sufficient to reject promotion because none shows standalone net profitability.

## Intraday Boundary

Order flow requires trades, quotes, or depth data. Liquidity sweeps and volume profiles
need intraday bars for defensible execution semantics. Anchored VWAP can be approximated
from daily bars, but not with intraday entry fidelity. Do not add these to the daily
scanner. First define a retained Kite intraday data contract and evaluate a separate,
BUY-only strategy through the same promotion gates.
