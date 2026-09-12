# Reliability Product Handoff

**Updated:** 2026-08-09  
**Current verdict:** Not ready for live, paid, or profit-reliability claims.

## Goal

Build a defensible halal-first NSE decision-control product that releases Telegram
swing signals only after it has point-in-time constituents, fundamentals, prices,
corporate actions, and halal classifications; survivorship-free portfolio
walk-forward evidence across regimes; statistically credible net benchmark
outperformance; 6-12 months of reconciled shadow trading; at least 99.5% verified
delivery; append-only signal snapshots; portfolio kill switches; and independent
quantitative, Shariah, and SEBI/RA legal approvals. Never promise profits.

## Completed Foundation

- Retained 2019-01-01 through 2024-06-30 NSE archive: 1,355 sessions,
  2,239,083 EQ bars, 2,601 symbols, and 902 symbols absent from the July 2024 snapshot.
- All 79 weekday archive gaps reconciled to 11 retained official NSE/NCL documents;
  SHA-256 verification reports zero unresolved dates and zero invalid sources.
  Report SHA-256: `6f0db0f5d6d0289dd748e3c16faae818836407642d4c598cf36954f1660b7ef6`.
- Point-in-time SQLite contracts, immutable source manifests, historical universes,
  dynamic liquidity universes, shared-capital simulation, and statistical gates.
- Correct next-open execution, OHLC stop/target handling, stop-first same-bar
  ambiguity, gap-stop behavior, costs, position limits, and regime testing.
- Deterministic point-in-time OHLCV adjustment supports reviewed factors, bonus,
  face-value splits, and cash dividends; unsupported price actions fail closed.
  Strict packet verification and single-snapshot audit reconciliation are implemented.
  Reviewed-factor authority is verifier-issued and non-forgeable, every non-automatic
  action enters the factor queue regardless of raw factor presence, and preflight binds
  the audit, packet manifest and CSV bytes, policy, baseline, and retained evidence.
- 1,681 XBRL filings discovered in 17 immutable batches. First 100 acquired:
  debt/assets 96%, annual revenue 99%, direct interest income 0%.
- Current candidate: 1,701 corporate equities, 99.706% price coverage, 86.71%
  business coverage, zero approved fundamental coverage, 226 business reviews,
  and 11 insurer specialist reviews outstanding. Controlled review templates now
  bind both queues to the retained source report; every decision remains pending.
- Append-only signal ledger and hash chain, transactional Telegram outbox,
  retries, idempotency, reconciliation, dead letters, governance, and kill switches.
- Append-only experiment registry contains seven retained `PREREGISTERED`
  residual-momentum versions; none is an evaluation result.
- Source sealing now tolerates bounded transient empty reads on regular files while
  retaining stable identity and byte-count checks; this prevents macOS false
  incomplete-read failures during preregistration.
- Approved private/public Telegram delivery now records one immutable signal and one
  idempotent, consent-bound outbox item per active chat, with approval rechecked at send
  time. The authenticated control server exposes `/readiness`, `/broker/holdings`, and
  `/broker/order-status`; paper actions remain the default. A Zerodha CNC adapter supports
  explicit gated placement, holdings-based exits, and order-status reconciliation.
- The frontend Release Readiness panel now reads the authenticated server decision and
  displays Telegram and broker capability states while preserving the current design.
- The Release Readiness panel also renders an authenticated activation checklist for
  release evidence, Telegram audience/delivery, Kite session, execution posture, and
  the operational kill switch; it is informational and cannot bypass a gate.
- Telegram enrollment now uses a secret-validated webhook. `/start terms-v1` records
  consent from Telegram's own chat ID, `/stop` revokes it, and the readiness response
  reports active recipient count, bot configuration, and webhook configuration. The
  `set_telegram_webhook.py` helper registers the HTTPS endpoint.
- Every queued recommendation now retains the consent version and consent timestamp;
  delivery rechecks that exact consent is still active before contacting Telegram.
- Multi-recipient Telegram briefings exclude operator-specific capital, portfolio, and
  performance metrics and include an educational-information disclaimer with `/stop`.
- Halal tier-change alerts now use the same approved audience/outbox path; the quarterly
  monitor no longer sends directly to `TELEGRAM_CHAT_ID`.
- Approved private/public dispatch now repeats per-symbol eligible-universe and halal
  checks before queueing, matching the shadow activation path.
- Signed Kite order postbacks are accepted only after API-secret checksum verification;
  verified status changes append to the broker lifecycle ledger.
- Telegram recommendation queueing now requires bot credentials before creating outbox
  rows, preventing credential-related dead letters after a release approval.
- `scripts/deliver_telegram_outbox.py` provides a one-shot scheduled retry worker;
  it refuses to touch the queue while release approval, kill-switch, or Telegram
  credentials are invalid and returns secret-free delivery-health JSON.
- The Telegram cockpit also exposes an authenticated **Retry due delivery** action
  that invokes this same consent/release/kill-switch-gated worker.
- Shadow-mode briefing rows now receive deterministic local acknowledgements instead
  of calling Telegram, so shadow delivery evidence cannot contact a user or dead-letter
  because the retired default-chat path is unavailable.
- Model/data drift alerts now use the consent-bound audience queue with a stable
  `drift:<hash>` signal identity; the old nonexistent direct `notify.send` path is gone.
- The legacy `src.web_dashboard` now binds to loopback and requires an explicit
  `X-Web-Trade-Token` for its paper mutation endpoints; without a token it is read-only.
- The legacy TradingView/Alpaca receiver now binds to loopback, requires
  `X-Webhook-Secret`, and rejects live Alpaca endpoints; the supported broker path is
  the authenticated Zerodha/Reliance control server.
- The legacy default-chat `_send()` shim is now inert; generic operational notices
  use the consent-bound audience/outbox helper, so no recommendation or alert path
  can silently fall back to `TELEGRAM_CHAT_ID`.
- GitHub Actions failure notices now use `scripts/queue_telegram_notice.py` through
  the same consent-bound outbox; direct `TELEGRAM_CHAT_ID` sends were removed from
  every scheduled workflow branch.
- The authenticated `/telegram/provider` endpoint and cockpit **Verify Bot & webhook**
  action perform secret-free Bot API `getMe`/`getWebhookInfo` checks against the exact
  configured HTTPS webhook URL.
- The cockpit **Register webhook** action and CLI helper share one HTTPS-only
  `setWebhook` implementation; responses never include the Bot token or secret and
  registration does not send recommendations.
- After provider verification, the Telegram panel exposes a `t.me` deep link that
  starts the current consent flow; it does not subscribe users automatically.
- The consent webhook now supports `/help` and `/status` in addition to exact-version
  `/start` and `/stop`; status replies reveal only the requesting chat's state.
- The cockpit now checks `/readiness` before BUY/CLOSE, presents paper fills separately
  from live Zerodha order acceptance, and provides order-ID status reconciliation. Live
  broker lifecycle events are appended to the existing hash-chained signal ledger under
  `broker:<order_id>`. Live manual execution is restricted to `BORO_LIVE_SYMBOL`, which
  defaults to `RELIANCE` and is surfaced in readiness.
- Live BUYs now require entry/stop/target values, place a two-leg OCO CNC GTT after the
  entry, return its GTT ID, and surface an explicit unprotected-entry warning if the
  protection request fails. Manual live closes require the GTT ID and cancel that
  protection only after confirming a sellable holding exists, preventing a stale
  trigger from submitting a second sell.
- The authenticated `/broker/reconcile` endpoint and cockpit action now reconcile
  holdings plus the daily order book, append lifecycle evidence, and flag orders
  outside the Reliance/NSE/CNC live scope.
- Direct gateway GTT cancellation now performs the same active-status and configured
  live-symbol validation as the control endpoint before issuing a DELETE request.
- Live BUYs enforce the platform's 2% maximum-loss rule and a 20% notional cap using
  `BORO_LIVE_CAPITAL`, `BORO_LIVE_MAX_RISK_PCT`, and `BORO_LIVE_MAX_NOTIONAL_PCT`.
- The broker gateway repeats the Reliance-only scope and BUY stop/risk checks for
  direct module callers; the read-only `/broker/risk-preview` endpoint and cockpit
  **Preview risk** control show the exact limits before live confirmation.
- Live BUY requests require a validated idempotency key and persist the completed
  result, so browser retries cannot submit a second identical broker order.
- Recommendation queueing and delivery both require the Telegram webhook secret,
  matching the readiness gate and preventing delivery from a pre-populated audience
  when enrollment security is missing.
- The frontend Telegram consent instruction now renders the configured current terms
  version instead of hardcoding `terms-v1`.
- The generic auto-close command is explicitly disabled in live mode; live positions
  rely on broker GTT protection and authenticated broker reconciliation instead of
  mutating the paper portfolio. The underlying `src.auto_close` module and scheduled
  CI path enforce the same fail-closed rule.
- The cockpit's positions endpoint now switches to authenticated Zerodha holdings in
  live mode and labels the table LIVE BROKER; paper holdings are never shown as live.
- After a live BUY or SELL, the cockpit now performs bounded automatic order-status
  reconciliation and checks the associated GTT when available; manual checks remain.
- The cockpit can request cancellation of open/pending regular CNC orders and records
  the cancellation request in the broker lifecycle ledger.
- The cockpit can retrieve and render the authenticated Zerodha daily order book,
  including open, pending, completed, and cancelled regular orders.
- `BORO_OPERATIONAL_KILL_SWITCH` blocks new live entries and recommendation delivery
  while keeping read-only broker reconciliation available; the readiness panel shows
  when the emergency pause is active.
- After a validated backend session, holdings, daily broker orders, order status, and
  GTT status remain observable while release approval blocks live mutations; placement,
  cancellation, and protection changes retain the live execution gates.
- An accepted BUY with failed protection is recoverable from the cockpit through the
  idempotent `POST /broker/gtt/protect` path; retries cannot create duplicate GTTs for
  the same request key, and successful recovery is ledger-recorded.
- The authenticated Telegram audience status now includes queued, retrying, delivered,
  dead-letter, and unreconciled outbox counts; recommendation queueing fails closed
  when dead-letter or unreconciled delivery incidents remain.
- Broker order and GTT cancellation now reconcile first and fail closed unless the
  instrument is the configured personal symbol (`RELIANCE` by default), the order is
  NSE/CNC, and the broker reports a cancellable pending state or active GTT.
- Direct GTT cancellation is also appended to the broker lifecycle ledger under a
  stable `broker:gtt:<id>` identity.
- The local control server defaults to loopback binding, exact localhost CORS,
  header-only token authentication, and a bounded request body; hosted deployment
  requires explicit bind/origin configuration and TLS.
- Telegram webhook updates are durably deduplicated by `update_id`, preventing
  provider retries from repeating consent processing or confirmation messages.
- The readiness card now retains the latest Zerodha session-validation result and
  offers an explicit readiness refresh, making live/paper operator state visible
  without relying on a transient toast.
- Live broker readiness now requires a recent successful `/broker/profile` check
  bound to the exact current access-token fingerprint; the frontend shows whether
  that session is verified.
- `python scripts/readiness_check.py --json` provides a machine-readable, read-only
  activation preflight without printing credentials.
- The Zerodha gateway enforces the same recent profile validation internally, so
  direct module callers cannot bypass the control-server session gate.
- The operational kill switch pauses new entries and Telegram delivery but preserves
  risk-reducing live exits, GTT cancellation, holdings, and order reconciliation.
- Zerodha session handling now has a backend-only login URL/request-token checksum
  exchange, token/profile validation, and an authenticated `/broker/profile` endpoint.
  The frontend exposes login, exchange, and validation controls without returning or
  storing the access token client-side; the exchange writes an owner-only token file.
  The documented `scripts/zerodha_session.py` command is directly executable and fails
  cleanly when `KITE_API_KEY` is absent.
- Live Reliance CLOSE requests now require a stable request ID and durable claim/finish
  record, matching BUY idempotency so browser retries cannot submit a second sell while
  the first broker order is still pending.
- File-backed Kite sessions now use the same owner-only token source for readiness
  fingerprinting as the broker gateway, so a successful cockpit login exchange remains
  validated after the token is persisted and the process environment is clean.
- Latest verification: focused Telegram/control/broker/tier/auto-close/outbox suite
  `123 passed`; complete repository suite `1357 passed in 424.81s`; residual-momentum
  file `34 passed` alone. Compliance remains
  rejected, audit SHA-256 `92086b8fc49a9d686756286deb1008f06da501ec946af955d36f99163ea83400`,
  with corporate-action review, PIT dataset, coverage, statistical, shadow, and
  quantitative/Shariah/legal approval blockers.

## Authoritative Strategy Evidence

Rule V1, monthly prior-60-session top-100 liquidity universe:

- 413 shared-portfolio trades; 99.38% return versus 107.11% NIFTYBEES.
- Annualized excess -0.61%; 95% CI -10.68% to 10.44%.
- Outperformance probability 45.95%; deflated-Sharpe probability 2.54%.
- Maximum drawdown 29.12%; bull, bear, and sideways gates all fail.
- Report: `results/dynamic-universe-ohlc-diagnostic-2020-2024.json`
- SHA-256: `411d256c3466a5ccb80e0e0a1a4af2569a31af2edd64d7734120ccda139bf155`

Rule V2 also fails: 63.91% versus 107.11%, 22.60% outperformance probability,
0.53% deflated-Sharpe probability, and 23.66% drawdown.

- Report: `results/dynamic-universe-v2-ohlc-diagnostic-2020-2024.json`
- SHA-256: `12bc2e21d435666d007053d5c4a4fe89b058ebb6135a152f4ea76c07184d61fe`

Earlier same-close, next-close, and close-only results are invalid for reliability
claims. Retain them for audit only. Treat 2020-2024 as burned strategy-selection data.

## Retained Preregistration

`nse-halal-residual-momentum-v7` is the current unopened seal at
`data/reliability/preregistrations/nse-halal-residual-momentum-v7.json` with canonical
SHA-256 `33a66476da97965cf964ffaf1eb82b2af60f7e8fdc4c04e9a2b9244fa9d12030`. Its fixed
protocol is NIFTY 500 against NIFTY 50 TRI GROSS, 2013-12-01 through 2014-12-31
warmup, 2015-01-01 through 2019-12-31 scored holdout, and 2020-01-01 through
2024-06-30 burned. It records six prior trials, an effective trial count of seven,
the frozen 365-day halal-classification freshness policy, and
`validation_values_opened: false`. No holdout values, scores, trades, report,
preflight, TRI, evaluation, or release authority exists. The registry SHA-256 is
`4cf51df2354a3ab61eb3f50cafacc69d84467ef085fb8472ef6102db85bfd964`; it has one
nested `protocol.experiment_id` event of type `PREREGISTERED`. All 14 retained v7
source hashes match current bytes at audit time. v7 supersedes unopened v6 without
changing strategy semantics.

v6 remains byte-preserved at SHA-256
`21efd568affe40c7139d38bd5a4fc258de1146df817acadaefa1042cb3d5c6b8`, but is
unopened and source-stale after governance hardening. Do not rewrite or evaluate it.

v5 is byte-preserved at SHA-256
`dd1988c0781489e0b823eda5cef3b3c14626ba4bd515c58ef83bdc6dd2e41cdc`.
Its source seal is invalid because macOS returned empty bytes for the non-empty,
evicted `corporate_action_review_packet.py` placeholder during preregistration.
The mismatch was found before preflight or validation access. v6 adds a stable,
complete-read check that rejects any source whose bytes do not match filesystem
size and metadata. v5 remains append-only evidence and must never be rewritten.

The v1 and v2 artifacts remain byte-preserved at SHA-256
`375038d938d41bc5d7abb191cb15c7674e446f7c12350ae008563d516792022a` and
`3810c0e2fa06df47fa6724a0f8f19020fa4757bbaff41abfa801f18f1ea3e68d`.
All v1-v6 artifacts are byte-preserved, superseded, and unevaluable because their
sealed source hashes are stale or invalid. v1-v7 each have only one retained
`PREREGISTERED` event and retain `validation_values_opened: false`.

## Key Code

- Data and PIT storage: `src/reliability/store.py`, `historical_universe.py`
- Portfolio evidence: `historical_portfolio.py`, `portfolio_simulator.py`
- Fundamentals and halal: `xbrl.py`, `filing_coverage.py`,
  `business_classification.py`, `shariah_policy.py`
- Operations: `ledger.py`, `outbox.py`, `activation.py`, `governance.py`
- Audits: `compliance_audit.py`, `experiment_registry.py`
- Holiday evidence: `holiday_reconciliation.py`,
  `data/reliability/historical/holiday-circular-manifest-2019-2024.json`
- Execution model: `src/backtest_runner.py`, `src/risk_manager.py`

## Blocking Gates

The audit must remain rejected for: incomplete point-in-time dataset and coverage,
failed statistical evidence, missing 180-365 day shadow evidence, and missing
quantitative, Shariah, and legal approvals. Also unresolved: point-in-time
corporate-action source coverage, official NIFTY 50 TRI, pending Shariah concept
mappings, unauthorized PDF reviewers, incomplete business reviews, and external
daily anchoring of the ledger hash head.

The retained source catalogue still contains duplicate eligible `corporate_actions`
records for 2024-01-01 through 2024-01-31 (lines 2 and 123, downloaded versus cached),
so it remains sealed and is never used directly for proposal indexing. Controlled
remediation produced a separate derived catalogue and the proposal CLI now indexes
that derived input successfully; this resolves the proposal-indexing defect only and
does not resolve any canonical data or governance gate.
The remediation utility is `src/reliability/corporate_action_catalogue_remediation.py`;
it emits a new hash-bound derived catalogue and removal manifest, never replaces the
sealed input. The full run completed: original catalogue SHA-256
`6b85ad34bff96d873843d090727faa257f9a3a263b784fef1af3f4c02e90ae9e`, derived
`data/reliability/corporate-action-announcement-smoke/source-catalogue-remediated.jsonl`
SHA-256 `d496add7cd3e40a5adebacb192c83c7781172a691aa8f4569351b22b71a762d4`, and
remediation manifest SHA-256
`ca4e7c4e12a127bb9274bc62b9996220ec0b827886a038bad3584597325b8428`. The derived
catalogue is proposal-only assistance, not a canonical source or approval; its isolated
index produced 1,057 rows (862 visibility, 195 factor). The retained proposal index is
`data/reliability/corporate-action-ai-proposals-20260809/evidence-index.jsonl`, SHA-256
`d0d54898f9342001ae8c65b54e1f170a0b6f63b1fab32e34726c6ddc5c973173`; its CLI manifest
records `proposal_only: true` and binds the two review CSV hashes.

The corporate-action backfill now covers all 66 required months from 2019-01 through
2024-06 with paired, hash-retained NSE action and announcement snapshots. Conservative
matching proves point-in-time visibility for 6,286/7,148 price actions. Explicit review
queues retain 862 unmatched/ambiguous visibility cases and 195 rights/merger/demerger
factor decisions. Every row is `PENDING`; accepted counts are zero. They await an
externally authorized human corporate-action reviewer; the current policy authorizes
nobody, and real-world reviewer identity or independence is not proven. Actual
adjusted-price backfill remains blocked because no factor review is approved.
Backfill report SHA-256:
`abde2b6e92123949af906005af27eca9364c338d385d57dd4b40c44a7394e798`.
Report: `results/corporate-action-readiness-2019-2024.json`; SHA-256:
`90964ce4e3f388fb8eb479db40a8326851aad111b116d9f7dc77a34bf6117308`.
Reviewed report: `results/corporate-action-reviewed-readiness-2019-2024.json`;
SHA-256: `d4f34e75f8839bba2c8b026b80de3926e8d25fcdd510358a19c147b4bd13d9f0`.

Reviewer packet: `data/reliability/corporate-action-reviews/`. Its manifest SHA-256 is
`d8cad6876de94c8923cddbab1a7c6a7c215687f00975ba8304eabb44025e07a1`.
Visibility template SHA-256:
`67ca98f7031d9a2988c6d7c19dad6f86ba8535b9535c0650046394d662b9608a`.
Factor template SHA-256:
`0cf5c1d19b9f4066bfd00b3ceb8a1a9af0368731fd5f2ccd90cc3613f92c9197`.
Reviewer policy: `data/reliability/corporate-action-review-policy.json`; SHA-256:
`ca19925bb12adafa92d9839b4a18278029dfabaddf4e8bad328548511a5b7d78`.
Required reviewer role: externally authorized human corporate-action data reviewer.
The canonical reviewed audit validates and directly hash-binds the packet, policy,
baseline report, CSV snapshots, retained evidence, and source snapshots. The internal
corrective review and dependency
audit found no remaining load-bearing defect; independent subagent re-review was
unavailable because the account quota was exhausted and is not claimed as approval.
No factor may be treated as production-authorized until an independent external
reviewer completes the controlled rows. Visibility acceptance requires a
retained primary document, matching SHA-256, reviewer identity, review time, and UTC
availability timestamp. Factor acceptance additionally requires a reproducible method
and factor in `(0, 1]`. Blank, ambiguous, unauthorized, or unsupported decisions remain
blockers.

Business and insurer reviewer packet:
`data/reliability/business-classification-reviews/`. Its manifest SHA-256 is
`ff2eb7ab4185f3caaacc6dba65c0df9a33b17584ce5d1489d1884b28a75ab7ea`.
It contains 226 primary-business rows and 11 insurer rows. Primary-business acceptance
requires retained primary evidence, matching SHA-256, a supported business type,
reviewer identity, and UTC review time. Insurer acceptance additionally requires an
explicit route from a qualified Shariah reviewer. All rows are pending and remain
fail-closed.

## Next Work Order

1. Task 5's AI evidence-proposal CLI is technically complete and independently reviewed;
   its remediated-catalogue proposal index is retained as non-authoritative assistance.
   It cannot authorize a reviewer, make canonical decisions, or clear a shadow or
   release gate.
2. After retained human authorization and governance-owner evidence exist, complete
   the 862 corporate-action visibility reviews and 195 rights/merger/demerger factor
   reviews, then rerun the reviewed audit and adjusted-price reproducibility. The
   reviewer workflow is in `docs/governance/CORPORATE_ACTION_REVIEWER_BRIEF.md`.
3. Obtain qualified Shariah decisions for accounting mappings, authorize two
   independent PDF reviewers, and independently resolve the prepared 226 business and
   11 insurer review rows; then regenerate classification coverage.
4. Finish XBRL batches only after concept policy approval; fail closed on ambiguity.
5. Keep v7 unopened and treat v6 as source-stale. v5 is retained as an invalid
   dataless-source seal; v1-v4 are superseded and source-hash stale.
   Do not tune on 2020-2024 or rewrite any retained artifact or registry row.
6. Acquire complete point-in-time NIFTY 500 holdout data plus official NIFTY 50 TRI,
   then pass aggregate-only preflight. Do not open holdout values or evaluate before
   that gate passes.
7. Start the 180-365 day shadow clock only after data and statistical gates pass.
8. Complete independent quantitative, Shariah, and SEBI/RA legal reviews.

## Task 7 Governance Addendum

`REJECTED` canonical decisions require retained human evidence, authorization, valid
timestamps, and rationale. Policy v2 is designed to retain human reviewer/governance
approval evidence, but no production principal is authorized; software cannot prove
real-world identity or independence. The current retained policy has an empty
`authorized_reviewers` list and no authoritative policy-v2 principal.

The opaque audit capability is process-local, exact-identity bound, source-revalidated
at use time, and required for shadow activation and release governance. Paths, hashes,
CLI flags, and AI output cannot create it. Daily dispatch and the compliance CLI provide
no such capability; they remain blocked and no Telegram signal is released. AI evidence
proposals are non-authoritative assistance only and cannot make canonical corporate-action
decisions.

The current compliance audit is rejected, SHA-256
`92086b8fc49a9d686756286deb1008f06da501ec946af955d36f99163ea83400`, with blockers
`CORPORATE_ACTION_REVIEW_MISSING`, data/PIT and coverage gaps, statistical evidence,
missing shadow evidence, and missing quantitative, Shariah, and legal approvals.
Quantitative, Shariah, and SEBI/RA legal approvals remain externally required.

Exact next work: obtain actual independent human corporate-action reviewer and governance-
owner evidence, then use the technically verified proposal CLI only as non-authoritative
assistance before any shadow or release gate can clear. The Task 6 deferred minor is only
a stale timestamp in an internal review package; sealed artifact metadata is correct.

## Verification

```bash
/tmp/boro-reliability-venv-20260728/bin/python -m pytest -q
/tmp/boro-reliability-venv-20260728/bin/python -m src.reliability.holiday_reconciliation \
  data/reliability/historical-holiday-review-2019-2024.json \
  data/reliability/historical/holiday-circular-manifest-2019-2024.json
/tmp/boro-reliability-venv-20260728/bin/python -m src.reliability.corporate_action_audit \
  data/reliability/corporate-action-announcement-smoke/source-catalogue.jsonl \
  --start 2019-01-01 --end 2024-06-30
/tmp/boro-reliability-venv-20260728/bin/python -m src.reliability.corporate_action_audit \
  data/reliability/corporate-action-announcement-smoke/source-catalogue.jsonl \
  --start 2019-01-01 --end 2024-06-30 \
  --review-packet-dir data/reliability/corporate-action-reviews \
  --reviewer-policy data/reliability/corporate-action-review-policy.json \
  --baseline-review-report results/corporate-action-readiness-2019-2024.json
/tmp/boro-reliability-venv-20260728/bin/python -m src.reliability.compliance_audit \
  data/reliability/current-release-evidence.json \
  --output results/current-compliance-audit.json
tail -n 6 data/reliability/experiment-registry.jsonl
```

The in-workspace `.venv-reliability` was evicted by macOS and is not reliable.
Use the external virtual environment above for verification.

The linked Git worktree metadata is broken and points to a missing parent repository.
Do not reset, checkout, clean, or attempt destructive Git repair. Preserve all files.

## Copy-Paste Continuation Loop Prompt

```text
Work in /Users/taaqibmasood/Documents/Web Dev & Saas/stocks project/V-1.0.

Read HANDOFF.md first, then README.md, PROOF_RESULT.md,
docs/governance/READINESS_STATUS.md, docs/governance/RELEASE_POLICY.md, and the
latest reliability plans under docs/superpowers/plans/. Inspect the repository
before acting; those files and retained artifacts are the authoritative state.

GOAL: Build a defensible halal-first NSE decision-control product that emits
reliable Telegram swing signals only after complete point-in-time market and
Shariah data, survivorship-free portfolio walk-forward tests, statistically
credible net benchmark outperformance across bull/bear/sideways regimes, 180-365
days of reconciled shadow trading, at least 99.5% verified idempotent delivery,
append-only signal evidence, kill switches, governance, and independent
quantitative, qualified Shariah, and SEBI/RA legal approvals. Never guarantee
profits and never enable live or paid signals while any gate fails.

Continue autonomously from the first incomplete item in HANDOFF.md's Next Work
Order. Keep me updated every meaningful step. Maintain an explicit plan and update
statuses incrementally. Use test-driven development for behavior changes. Preserve
the two signal paths and trace every live-rule change to scanner.py. Fail closed on
missing, stale, ambiguous, or unapproved data.

Do not optimize or select strategies using the burned 2020-2024 evaluation period.
Pre-register every new strategy/protocol before untouched evaluation. Store every
report immutably and append its SHA-256, assumptions, and verdict to the experiment
registry. Include realistic next-open execution, OHLC stop/target resolution,
costs, shared capital, liquidity, position limits, corporate actions, delistings,
and an official total-return benchmark.

For each work cycle: inspect -> plan -> implement -> run focused tests -> run the
full suite -> regenerate evidence/audit -> update README, PROOF_RESULT,
READINESS_STATUS, and HANDOFF. Do not revive superseded headline returns. Do not
ask repetitive approval questions when the next safe task is discoverable. If an
external decision blocks progress, complete every independent internal task first,
then record the exact evidence, owner, and acceptance criteria needed. Continue
until the complete release audit passes with real retained evidence or a genuine
external blocker prevents further work.
```
