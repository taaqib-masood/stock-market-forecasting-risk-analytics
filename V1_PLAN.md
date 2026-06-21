# V-1.0 Plan — "Prove the Edge First" (post-council cut)

> This is the canonical plan of record. It supersedes the broader scope in `docs/UPGRADE_EXTRACTION.md` (kept as a reference backlog). The full original plan was pressure-tested with a 5-advisor council; the verdict was that it decorated an edge that hasn't been proven. So V-1.0 is now a **proof, not a product.**

## The one question V-1.0 must answer
Does an **India, 🟢-halal-only** strategy show an **edge that survives realistic costs** — measured on **ONE unified code path**, with leakage controls?

If no → none of the deferred features were worth building.
If yes → we've *earned* the right to scale, and the rest comes off the shelf with data behind each decision.

## In scope (the proof) — sequenced
1. **Regression tests** — `risk_manager` (the 10+ rules) + paper-trade P&L. Safety net before any refactor. Pick the 3 rules that lose real money if broken; assert against known inputs.
2. **Unify the two code paths** — the live `scanner.py` and the `pipeline.py` backtest currently run *different* logic. Collapse them: one canonical strategy/signal function called by both live and backtest. *This is the #1 priority* — until it's done, every metric describes a system we don't trade.
3. **Leakage / look-ahead detection** — audit features for future-data leakage (freqtrade `lookahead-analysis` concept). Must precede any threshold tuning.
4. **With-cost metrics** — IC, ICIR, Information Ratio, returns net of slippage + commission (standard quant report; extends `metrics.py`).
5. **Point-in-time halal universe** — halal status is *time-varying* (a stock's debt crosses 33% → becomes non-compliant mid-history). Badging *today's* list across history is itself look-ahead leakage. For the proof: use the current 🟢 list but **carry an explicit survivorship caveat**; reconstruct point-in-time via OpenBB fundamentals before trusting a positive result.
6. **India 🟢-only backtest** on the unified path → the verdict.

## Deferred behind the edge gate (build only on a positive proof)
- 🟡/🔴 badging engine + cumulative haram-exposure / purification tracker
- riba-financials opt-in
- multi-market: US, Saudi (Tadawul), then UAE
- barakah sleeve + Zakat wiring
- qlib Alpha158 factor library, optuna hyperopt, full Lean 5-stage refactor
- the "halal-as-a-service" business direction (a real V2+ prize — gated on a proven, scholar-governed screen)

## Retained decisions
- Halal philosophy = pragmatic AAOIFI — but for the *proof*, a binary 🟢/not-🟢 filter (no 🟡 trading yet).
- ruflo not adopted.
- Work in the V-1.0 worktree; keep `main` clean.

## Honest caveats the council surfaced
- **Self-authored fiqh has no governance** — the tiering logic needs an external scholar before any public/commercial use; a one-time sign-off isn't a maintained ruling.
- **Distribution = liability the moment it goes public** — public buy signals + Zakat/purification figures are unlicensed investment advice (SEBI RA) + de-facto religious rulings. Latent now (private Telegram); critical before sharing.
