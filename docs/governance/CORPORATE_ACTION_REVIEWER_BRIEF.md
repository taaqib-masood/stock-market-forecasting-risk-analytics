# Corporate-Action Reviewer Brief

**Status:** External review required. This brief does not authorize a reviewer or
approve any decision.

The current compliance audit is rejected (`approved: false`), and the production policy
authorizes no principal. V6 is unopened but source-stale; v7 is the current unopened
14-source seal with `validation_values_opened: false`, no performance evidence, and no
release authority. Quantitative, qualified Shariah, and SEBI/RA legal approvals remain
external requirements.

## Scope

Review the retained packet at `data/reliability/corporate-action-reviews/`:

- `visibility-reviews.csv`: 862 unresolved point-in-time visibility cases.
- `factor-reviews.csv`: 195 rights, merger, or demerger factor cases.
- `manifest.json`: immutable queue identities and source-report binding.

Every row begins as `PENDING`. Do not remove, add, reorder, or change any identity
field: `review_id`, `symbol`, `action_type`, `ex_date`, `purpose`, or `reason`.

## Governance Before Review

An independent governance owner must create and retain a new reviewer-policy version
that names the reviewer in `authorized_reviewers`, excludes that reviewer from
`prohibited_reviewers`, and retains the permitted HTTPS evidence hosts. The retained
approval record must identify the human reviewer, permitted scopes and validity window,
non-revocation status, reviewer-independence evidence, a distinct governance owner,
the owner's approval timestamp, and hashes of the supporting governance evidence. The
current policy intentionally authorizes nobody and explicitly prohibits `codex` and
`taaqib-masood`.

Do not modify the existing policy to fabricate approval. Reviewer authorization,
evidence collection, and the completed CSVs must be independently retained before an
operator runs reconciliation. AI evidence proposals may assist research only; they
cannot make canonical corporate-action decisions or create reviewer authority.

## Activation Boundary

Shadow activation and release governance require a process-local, exact-identity-bound,
source-revalidated-at-use-time opaque audit capability. It cannot be created by a path,
hash, CLI flag, or AI output. The daily dispatcher and compliance CLI intentionally
provide no capability, remain blocked, and cannot release a Telegram signal.

## Evidence Rules

For every `CONFIRMED` visibility row, `APPROVED` factor row, or `REJECTED` row,
retain a primary document under `data/reliability/corporate-action-reviews/evidence/`
and enter:

- a relative, regular, non-symlink `evidence_path` below `evidence/`;
- its SHA-256 in `evidence_sha256`;
- an HTTPS `evidence_source_url` on an allowed policy host;
- `confirmed_available_at` and `reviewed_at` as RFC 3339 UTC timestamps;
- an authorized `reviewer_id` and concise `notes`.

Availability must be earlier than the ex-date 09:15 Asia/Kolkata market open, and
review time cannot precede availability. Future timestamps are rejected.

For `APPROVED` factors, additionally enter an `adjustment_factor` in `(0, 1]` and a
nonblank, reproducible `method`. Use `REJECTED` when retained evidence does not support
the queue item; its evidence, authorization, timestamps, and rationale remain mandatory,
but it does not require an adjustment factor or method. Both `PENDING` and `REJECTED`
leave the release gate blocked.

## Operator Verification

After independent authorization and review submission, run:

```bash
/tmp/boro-reliability-venv-20260728/bin/python -m src.reliability.corporate_action_audit \
  data/reliability/corporate-action-announcement-smoke/source-catalogue.jsonl \
  --start 2019-01-01 --end 2024-06-30 \
  --review-packet-dir data/reliability/corporate-action-reviews \
  --reviewer-policy data/reliability/corporate-action-review-policy.json \
  --baseline-review-report results/corporate-action-readiness-2019-2024.json \
  --output results/corporate-action-reviewed-readiness-2019-2024.json
```

Then run the full test suite and the adjusted-price reproducibility checks. Do not
backfill prices, preregister another strategy, run preflight, expose holdout values,
or enable signals merely because some rows pass. Release remains blocked until every
independent data, statistical, shadow-delivery, and legal/Shariah gate passes.
