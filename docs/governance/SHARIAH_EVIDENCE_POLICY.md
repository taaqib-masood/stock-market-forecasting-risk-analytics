# Shariah Evidence Policy

`config/shariah-accounting-policy.json` is the machine-readable authority for
ambiguous accounting mappings. Repository contributors must not convert a candidate
such as lease liabilities, cash-flow interest adjustments, or deposit interest into a
screening fact while its decision is `PENDING` or `REJECTED`.

An `APPROVED` decision requires `approved_by`, `evidence_uri`, and `effective_from`.
The evidence must identify a qualified Shariah authority and the reviewed methodology.
Every promoted fact records the decision ID and policy version.

Image-based filing facts require two distinct reviewers listed in
`authorized_data_reviewers`. Matching numbers are still non-tradeable when any required
fact is missing. Disagreements fail reconciliation and must be resolved against the
primary filing, never averaged.

Business screening runs before financial ratios:

- `CONVENTIONAL_BANK`, `CONVENTIONAL_NBFC`, and `CONVENTIONAL_LENDER` are excluded.
- `INSURER` requires a qualified specialist review and remains non-tradeable.
- `NON_FINANCIAL` proceeds to debt and impermissible-income ratio screening.
- Missing or unknown business types remain `UNKNOWN` and non-tradeable.

Policy changes require a new `policy_version`, retained review evidence, regression
tests, and the release-level Shariah approval defined in `reliability-policy.json`.
