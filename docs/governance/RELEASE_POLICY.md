# Reliability Release Policy

## Modes

- `research`: offline experiments only; outputs cannot be distributed as signals.
- `shadow`: timestamped Telegram candidates with simulated fills; no broker orders.
- `private`: limited self/family use only after statistical and operational gates pass.
- `public`: blocked until all quantitative, Shariah, and SEBI/RA legal evidence is current.

Mode promotion is controlled by `config/reliability-policy.json` and evaluated by
`src.reliability.governance.evaluate_release`. Editing documentation or environment
variables cannot bypass a failed gate.

## Required Evidence

Every promoted strategy must identify an immutable strategy version, point-in-time
dataset manifest, untouched statistical report, and reconciled shadow period. The
quantitative reviewer must be independent of the experiment author. Shariah and legal
reviews must name the reviewer, link to retained evidence, and include an expiry date.

## Strategy Changes

Any entry, exit, position-sizing, universe, cost, or regime-rule change creates a new
strategy version and restarts statistical review. Material changes restart the shadow
observation clock. Emergency risk reductions may be deployed immediately but must be
recorded as ledger events and reviewed before normal operation resumes.

## Fail-Closed Rule

Unknown or stale data, unresolved corporate actions, expired approvals, broken audit
chains, delivery failures, drift alerts, or portfolio-limit breaches block new entries.
Risk management for existing positions continues.

