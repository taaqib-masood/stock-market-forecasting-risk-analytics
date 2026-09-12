# Reliability Incident Response

## Immediate Actions

1. Set reliability mode to `research` and block new entries.
2. Continue monitoring stops, targets, and existing-position risk.
3. Record an `INCIDENT_OPENED` ledger event with timestamps, affected signals, data
   manifests, strategy version, and observed impact.
4. Preserve the database and source files; do not rewrite ledger or outbox records.

## Severity

- Critical: incorrect or duplicate public signal, audit-chain failure, legal/Shariah
  breach, or risk-limit bypass.
- High: stale/incorrect market data, unresolved corporate action, missed alert, or
  strategy/live divergence.
- Medium: delayed alert recovered within the delivery SLO or non-signal reporting error.

## Recovery

Corrective code requires a regression test. Reconcile every affected signal and issue a
clear correction through the original delivery channel. Record root cause, scope,
timeline, financial impact, and preventive action. Close the incident with an
`INCIDENT_RESOLVED` event only after independent review.

Any unresolved Critical or High incident blocks release promotion and resets the clean
operating interval when it invalidates shadow evidence.

