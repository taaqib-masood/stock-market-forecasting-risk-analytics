# Reliability Readiness Status

**Updated:** 2026-08-01  
**Current mode:** Source acquisition and shadow runtime implemented; activation blocked.

## Implemented

- SQLite point-in-time contracts for NSE membership, bars, corporate actions,
  fundamentals, and halal classifications.
- Provider-neutral, SHA-256-manifested bundle imports with fail-closed missing ratios.
- Bounded NSE archive acquisition with legacy/UDiFF naming, retries, ZIP/GZIP
  validation, atomic retention, extraction, and append-only source cataloguing.
- Retained corporate-action and financial-result API snapshots plus allowlisted XBRL
  acquisition and conservative debt/assets, revenue, and interest-income extraction.
- Deterministic backward OHLCV adjustment for visible bonus, split, dividend, and
  independently reviewed factors; unsupported price actions fail closed.
- Strict review-packet verification binds deterministic IDs, immutable queue fields,
  source and template hashes, authorized reviewers, retained evidence, and timestamps.
- Baseline and reviewed corporate-action audits reconcile one retained source snapshot;
  accepted factor overlays preserve exact provenance, and adjustment-boundary controls
  reject missing, ambiguous, unapproved, or out-of-scope factors.
- BSE primary-filing fallback with immutable PDF retention and two-independent-reviewer
  reconciliation. Single reviews, disagreements, and incomplete concepts fail closed.
- Versioned Shariah accounting decisions, authorized PDF reviewer controls, and
  business-first screening that excludes conventional lenders and routes insurers for
  specialist review before ratio classification.
- Independent point-in-time business-classification storage, bundle ingestion, historical
  lookup, and activation coverage checks. Present-day labels cannot leak into old backtests.
- Deterministic full-universe XBRL batching with per-batch hashes, annual-duration context
  selection, instant balance contexts, and retained ambiguous interest concepts.
- A retained 2019-01-01 through 2024-06-30 bhavcopy archive and dedicated historical
  database containing 1,355 sessions, 2,239,083 EQ bars, and 2,601 symbols. Session-level
  tradable universes include 902 symbols absent from the July 2024 snapshot.
- Backfill reconciliation that distinguishes holidays, absent reports, exchange misses,
  transport failures, and retained-file hash failures before bundle generation.
- Reconciliation of all 79 weekday archive gaps to 11 retained official NSE/NCL
  documents, with SHA-256 verification and zero unresolved dates.
- Block-bootstrap benchmark excess-return confidence intervals, deflated Sharpe
  probability, no-leak rolling windows, and required regime evaluation.
- Next-bar signal execution and shared-capital portfolio simulation with concurrent
  position limits, confidence ranking, daily mark-to-market, and retained benchmark data.
- Append-only SQLite signal ledger with update/delete guards and a verifiable global
  hash chain.
- Transactional Telegram outbox with idempotency keys, leased claims, exponential
  retries, dead letters, and delivered-but-unreconciled quarantine.
- Portfolio controls for stale data, halal status, drawdown, exposure, sector
  concentration, correlation, drift, corporate actions, and delivery health.
- Machine-readable release policy requiring 180 shadow days, at least 99.5%
  reconciled delivery, zero duplicates/incidents, reproducible statistical evidence,
  and current quantitative, Shariah, and legal approvals.
- Canonical unopened preregistration of `nse-halal-residual-momentum-v7` at
  `data/reliability/preregistrations/nse-halal-residual-momentum-v7.json`, SHA-256
  `33a66476da97965cf964ffaf1eb82b2af60f7e8fdc4c04e9a2b9244fa9d12030`. The protocol
  fixes NIFTY 500, NIFTY 50 TRI GROSS, 2013-12-01 through 2014-12-31 warmup,
  2015-01-01 through 2019-12-31 scored holdout, and 2020-01-01 through 2024-06-30
  burned data. It has six prior trials, an effective count of seven, a frozen
  365-day halal freshness policy, and has opened no validation values or evaluation.
  V7 has current hashes for an exact 14-source seal and supersedes byte-preserved,
  source-stale v6 (`21efd568affe40c7139d38bd5a4fc258de1146df817acadaefa1042cb3d5c6b8`).
  v5 is byte-preserved as an invalid unopened seal because an evicted non-empty source
  was hashed as empty. Each version has one `PREREGISTERED` event and no evaluation event.
- Canonical corporate-action decisions now fail closed: `REJECTED` requires retained
  human evidence, authorization, UTC timing, and rationale. Policy v2 can retain a
  human reviewer and separate governance-owner approval record, but the production
  policy authorizes nobody and software cannot prove real-world identity or independence.
- The sealed corporate-action catalogue remains unchanged. A hash-bound derived
  catalogue was used to build a proposal-only evidence index with 1,057 rows (862
  visibility, 195 factor) at
  `data/reliability/corporate-action-ai-proposals-20260809/evidence-index.jsonl`,
  SHA-256 `d0d54898f9342001ae8c65b54e1f170a0b6f63b1fab32e34726c6ddc5c973173`.
  This resolves proposal indexing only; it is not canonical evidence or approval.
- Preregistration source sealing now retries up to two transient empty reads before
  failing closed on an incomplete or unstable regular file. Its identity check uses
  immutable file identity and size plus two byte-hash passes, so filesystem timestamp
  metadata drift cannot create a false instability result. The complete repository
  suite passes `1357` tests; this changes no release or approval requirement.
- Approved private/public Telegram delivery is now wired to the append-only ledger and
  transactional outbox: each active recipient requires explicit consent, receives a
  stable idempotency key, and is rechecked against release approval before send. The
  control server exposes `/readiness`, `/broker/holdings`, and `/broker/order-status`.
  The Zerodha CNC adapter remains disabled until either release approval or the private
  owner acknowledgement, live-mode confirmation, and credential validation.
- The dashboard Release Readiness panel pulls the authenticated server decision and shows
  Telegram/broker channel availability without enabling blocked actions.
- Private owner Reliance execution is now separated from public recommendation release:
  `BORO_PERSONAL_LIVE_TRADING_ACK=I_UNDERSTAND_PERSONAL_LIVE_TRADING` plus live mode,
  recent Kite validation, and the existing risk/confirmation gates can enable personal
  CNC orders in `private` mode. This does not approve Telegram distribution or paid signals.
- The same panel renders an authenticated activation checklist for release blockers,
  Telegram audience/delivery health, Kite session state, execution posture, and the
  operational pause without changing any gate decision.
- Telegram enrollment is implemented as a secret-validated webhook: `/start <terms-version>`
  records explicit consent using Telegram's supplied chat ID, while `/stop` revokes it.
  `scripts/set_telegram_webhook.py` registers the HTTPS endpoint. No recommendation is
  sent by the enrollment confirmation, and an empty or revoked audience keeps the channel
  unavailable.
- Recommendation outbox payloads retain the recipient's consent version/timestamp and
  delivery refuses payloads whose exact consent is no longer active. The focused
  Telegram/broker/control/tier/auto-close/outbox suite passes `123` tests and the
  complete repository verification suite passes `1357` tests; independent release evidence
  remains unchanged.
- Scheduled GitHub Actions notices also use the consent-bound outbox helper; no workflow
  branch directly posts to a configured chat ID outside the audience registry.
- Shadow-mode briefing delivery uses deterministic local acknowledgements and never
  contacts Telegram; only approved private/public modes invoke the provider sender.
- Drift alerts use the same consent-bound outbox and stable signal identity as other
  operational notices; they remain gated when release evidence is incomplete.
- `scripts/deliver_telegram_outbox.py` supplies a one-shot retry worker for scheduled
  deployments; it is fail-closed on release/kill-switch/credential blockers and reports
  dead-letter and unreconciled health without exposing payloads or secrets.
- The authenticated Telegram cockpit can invoke that same worker through
  `/telegram/outbox/retry`, keeping manual recovery on the identical gated path.
- Private/public delivery repeats the per-symbol universe and halal gates used by shadow
  activation before it can create any recipient outbox entries.
- Recommendation queueing also requires a configured Telegram bot token before creating
  outbox rows; missing credentials fail closed without generating dead letters.
- Telegram briefings are audience-safe: operator portfolio metrics are not broadcast,
  and every recommendation includes risk/disclaimer and unsubscribe instructions.
- Halal tier-change alerts also use the consent-bound recommendation outbox; direct
  default-chat delivery is no longer used by the tier monitor.
- The legacy default-chat send shim is inert; generic operational messages now use the
  same consent-bound outbox and release gate as recommendations.
- Recommendation queueing and delivery both require the Telegram webhook secret,
  matching the readiness gate even if an audience database already contains consent rows.
- The Telegram panel renders the current terms version returned by the control server,
  keeping the user enrollment command aligned after a terms rotation.
- The authenticated `/telegram/provider` check verifies Bot API identity and exact
  webhook registration using `getMe`/`getWebhookInfo`; secrets are never returned to
  the frontend.
- The authenticated `/telegram/webhook/register` action shares the CLI's HTTPS-only
  `setWebhook` path and returns only secret-free registration status.
- Telegram users can request `/help` or `/status`; `/status` checks only the caller's
  exact current consent version and does not disclose the audience registry.
- Kite session exchange is backend-only: the one-time request token is combined with the
  API key and secret for the documented checksum exchange, and `/broker/profile` validates
  the resulting access token without exposing personal fields to the dashboard.
- The authenticated cockpit can open `/broker/login-url` and POST the one-time token to
  `/broker/session/exchange`; the resulting access token is atomically stored with 0600
  permissions in the ignored backend token file and only safe profile metadata returns.
- Signed Kite order postbacks are accepted at `/broker/postback` only after checksum
  verification with the backend API secret; verified status updates append to the broker
  lifecycle ledger.
- Live Reliance CLOSE requests now require a stable request ID and durable idempotency
  record, preventing browser retries from submitting duplicate sells before fill
  reconciliation completes.
- The local cockpit checks readiness before every BUY/CLOSE action, distinguishes a
  broker-accepted order from a confirmed fill, and exposes order-status reconciliation.
  Accepted live order and status events are appended to the hash-chained ledger under
  `broker:<order_id>` for post-trade review. Live manual execution is restricted to
  `BORO_LIVE_SYMBOL` (default `RELIANCE`) and the scope is returned by `/readiness`.
- Live BUY risk is bounded by the shared 2% maximum-loss rule and a 20% notional cap;
  both limits and the configured capital are returned by `/readiness`.
- The authenticated read-only `/broker/risk-preview` preflight returns the exact
  Reliance risk, notional, stop/target, and two-leg GTT checks before confirmation;
  the gateway repeats symbol and BUY risk validation for direct callers.
- After `/broker/profile` validates the backend session, holdings, daily broker orders,
  order status, and GTT status are read-only observable even while release approval
  blocks live mutations; placement and cancellation retain the live execution gates.
- If an accepted live BUY lacks protection because the provider call fails, the cockpit
  offers an idempotent OCO recovery endpoint; recovery remains subject to the Reliance,
  session, risk, and release gates and is appended to the broker ledger.
- Live BUY requests are idempotent: the request key and final broker response are
  retained in the reliability database and replayed on a matching retry.
- The paper auto-close command fails closed in live mode so it cannot be mistaken for
  live broker position management; the underlying module also guards scheduled CI runs.
- Live cockpit positions are sourced from authenticated Zerodha holdings and visibly
  labelled LIVE BROKER; paper positions remain labelled PAPER.
- The frontend automatically reconciles accepted live orders for a bounded period and
  checks the associated GTT, while retaining manual status controls.
- Open or pending regular CNC orders can be cancelled through the authenticated cockpit
  endpoint and the request is recorded in the broker ledger. The cockpit can also
  retrieve and render the authenticated Zerodha daily order book, including open,
  pending, completed, and cancelled regular orders.
- `BORO_OPERATIONAL_KILL_SWITCH` provides an operator-controlled fail-closed pause for
  new live entries and recommendation delivery; the frontend displays its active state.
- Telegram readiness now exposes outbox health in the authenticated audience response;
  dead-letter and delivered-but-unreconciled incidents block further recommendation
  queueing until reviewed.
- Broker order and GTT cancellation reconcile broker-reported scope and status first;
  non-Reliance, non-CNC, completed, inactive, or otherwise unverified controls are
  rejected before a cancellation request is sent.
- Direct GTT cancellation is retained in the broker lifecycle ledger under
  `broker:gtt:<id>` for post-trade review.
- Authenticated `/broker/reconcile` now reconciles holdings and the daily order book,
  records broker lifecycle evidence, and reports non-Reliance/non-NSE/non-CNC scope
  issues to the cockpit operator.
- Direct broker-gateway GTT cancellation also validates active status and the configured
  live symbol before sending a DELETE request, so module callers cannot bypass scope
  checks.
- The control server defaults to loopback binding, exact local CORS, header-only token
  authentication, and bounded request bodies; hosted use requires explicit origin,
  bind, and TLS configuration.
- Telegram webhook updates are durably deduplicated by provider `update_id`, so retry
  delivery cannot duplicate consent processing or confirmation messages.
- The frontend readiness card retains broker-session validation state and provides an
  explicit refresh action for the operator.
- Live broker readiness requires a recent successful `/broker/profile` validation for
  the exact current access-token fingerprint; changing the token invalidates it.
- `python scripts/readiness_check.py --json` provides a secret-safe machine-readable
  preflight for the required Telegram and broker channels.
- The Zerodha gateway independently enforces the recent profile validation, preventing
  direct module callers from bypassing the session gate.
- The operational kill switch pauses new entries and Telegram delivery while retaining
  risk-reducing live exits, GTT cancellation, holdings, and order reconciliation.
- Live BUYs require a validated entry/stop/target ordering and submit a two-leg OCO
  CNC GTT protection trigger; the response exposes the GTT ID and the cockpit can
  reconcile or cancel it. Manual live closes require that ID and only cancel it after
  confirming a sellable holding exists.
- Shadow activation and release governance require a process-local, exact-identity-bound,
  source-revalidated-at-use-time opaque audit capability. The daily dispatcher and
  compliance CLI explicitly supply no capability and remain blocked; paths, hashes, CLI
  flags, and AI output cannot create it. AI proposals cannot make canonical decisions.

## Activation Blockers

1. No delisted-inclusive, production point-in-time NSE bundle has been imported into
   `results/reliability.db`. The bundle must now include complete point-in-time business
   classification history as well as membership, prices, actions, and fundamentals.
   Daily bhavcopies now provide survivorship-free tradable-universe evidence for the test
   window, but they are not a substitute for a complete legal listing/delisting register.
2. A reconciled 2024-07-01 through 2024-07-05 candidate contains five complete
   bhavcopies and one active-equity security snapshot. It identifies 1,909 active EQ
   instruments, including 1,701 corporate equities after fund and DVR exclusions, and
   reaches 99.706% corporate price coverage; five symbols have no retained bar:
   `AKSHAR`, `AKSHOPTFBR`, `UMAEXPORTS`, and `VERTOZ` traded under the excluded `BE`
   series on all five sessions; `EMBDL` has no retained bar. These are now reported as
   alternate-series and no-trade gaps rather than generic ingestion failures.
   Point-in-time business coverage is 1,475/1,701 (86.71%); 226 issuers require primary
   business review, and 11 identified insurers are separately queued for specialist review.
3. Candidate fundamental coverage is 0%. Production annual XBRL coverage and approved
   handling for absent interest-income concepts are required before halal classification.
   Announcement-time corporate actions and delisted-inclusive history also remain incomplete.
   The corporate-action source audit covers all 66 months from 2019-01 through 2024-06
   with paired, hash-retained NSE action and announcement snapshots. It proves
   point-in-time visibility for 6,286/7,148 price actions. The no-review report SHA-256
   is `90964ce4e3f388fb8eb479db40a8326851aad111b116d9f7dc77a34bf6117308`; the pending
   reviewed report SHA-256 is `d4f34e75f8839bba2c8b026b80de3926e8d25fcdd510358a19c147b4bd13d9f0`.
   The retained review queues contain 862 unmatched/ambiguous visibility cases and 195
   rights/merger/demerger factor decisions, all `PENDING` and awaiting an externally
   authorized human reviewer. The current policy authorizes nobody, and neither the
   reviewer's real-world identity nor independence is proven. The packet manifest
   SHA-256 is `d8cad6876de94c8923cddbab1a7c6a7c215687f00975ba8304eabb44025e07a1`;
   the reviewer-policy SHA-256 is
   `ca19925bb12adafa92d9839b4a18278029dfabaddf4e8bad328548511a5b7d78`.
   Controlled CSV templates require primary-document hashes, reviewer identity, review
   timestamps, and reproducible factors; blank or ambiguous decisions fail closed.
   Actual adjusted-price backfill remains blocked because no factor review is approved.
   After separating fund units from corporate equities and reconciling symbol changes by
   ISIN, historical filing discovery finds point-in-time XBRL for 1,681 of 1,701 eligible
   symbols (98.82%). The 20 unresolved symbols comprise nine insurers requiring a separate
   business screen, four filings only available after the cutoff, and seven symbols with no
   retained NSE filing metadata. BSE fallback recovered pre-cutoff filings and primary
   PDFs for `ABBOTINDIA`, `AMIORG`, `BAYERCROP`, `DTIL`, and `MCX`; `GODHA` remains
   source-missing and `IBULHSGFIN` needs financial-business routing. These PDFs remain
   excluded from normalized fundamentals until two independent reviews agree on every
   required concept. The first `ABBOTINDIA` review confirms assets and revenue but leaves
   debt and interest income unresolved; lease liabilities and cash-flow interest are only
   candidates pending policy approval. The 1,681 discovered XBRL filings are partitioned into
   17 immutable batches. The first 100-document batch completed without transport failures;
   debt/assets was available for 96, annual revenue for 99, but direct interest income for 0.
   Candidate tags were retained with provenance: annual interest adjustment (96), investing
   and operating interest receipts (97 each), and financial-company interest earned (9).
   None are promoted or combined without qualified Shariah approval.
4. `daily_briefing` is wired behind `BORO_RELIABILITY_MODE=shadow`, but the repository
   variable must remain unset until `src.reliability.activation` passes.
5. Current strategy evidence fails release gates. On the frozen 2019-liquidity universe,
   both RuleStrategy variants have excess-return confidence intervals crossing zero,
   deflated-Sharpe probabilities below 5%, drawdowns above 20%, and failures in bull,
   bear, and sideways regimes. See `PROOF_RESULT.md`.
   Under corrected next-open and intraday-OHLC execution, the monthly point-in-time
   liquidity diagnostic underperforms NIFTYBEES, has only 45.95% probability of
   outperformance, 2.54% deflated-Sharpe probability, 29.12% drawdown, and fails every
   regime. Earlier higher returns are superseded execution artifacts.
6. The 180-day clock has not started. It starts only after the first fully versioned,
   reconciled shadow signal.
7. Independent quantitative, qualified Shariah, and SEBI/RA legal reviews are external
   evidence and remain outstanding. All three ambiguous accounting mappings in
   `config/shariah-accounting-policy.json` remain `PENDING`, and no PDF data reviewers
   are authorized yet.
8. Hash-chain heads need an external daily anchor before the ledger can be described as
   independently tamper-evident across database replacement.
9. The v7 preregistered residual-momentum experiment still needs complete point-in-time
   NIFTY 500 holdout data plus official NIFTY 50 TRI, followed by aggregate-only
   preflight. Compliance remains rejected; no test result is an evaluation verdict.

## Next Work Order

1. The AI evidence-proposal CLI is technically complete and independently reviewed, but
   remains non-authoritative assistance only; it cannot authorize a reviewer or clear a
   release gate.
   It cannot make canonical corporate-action decisions, grant reviewer authority, or
   clear any shadow or release gate.
2. After retained human authorization and governance-owner evidence exist, an external
   reviewer must complete all 862 visibility and 195 factor reviews. Then rerun the
   reviewed audit and adjusted-price reproducibility. Do not backfill adjusted prices
   while approved factor count remains zero.
3. Continue holdout and TRI readiness only after the corporate-action review boundary
   is reproducible. Do not open validation values or run preflight/evaluation early.

## Next Activation Command

After generating a normalized bundle:

```bash
python -m src.reliability.importers data/reliability/nse-bundle.json \
  --db results/reliability.db --ruleset-version aaoifi-v1
```

Then verify coverage only. Do not set `BORO_RELIABILITY_MODE=shadow` unless activation
has received the required opaque audit capability and every applicable gate is satisfied.
Public or paid signals remain prohibited until `evaluate_release` returns `approved: true`
using real, retained evidence.
