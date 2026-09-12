# Point-in-Time Data Contract

Reliability imports use normalized JSON bundles. Provider adapters may download NSE
reports or parse XBRL, but evaluation reads only imported records from
`ReliabilityStore`. This keeps network behavior outside backtests.

```json
{
  "source": "nse-bhavcopy-and-filings",
  "available_at": "2026-07-10T18:00:00Z",
  "metadata": {"source_url": "https://www.nseindia.com/all-reports"},
  "memberships": [
    {"symbol": "RELIANCE", "valid_from": "2026-07-10", "valid_to": null}
  ],
  "bars": [
    {"symbol": "RELIANCE", "session_date": "2026-07-10", "open": 1,
     "high": 1, "low": 1, "close": 1, "volume": 1}
  ],
  "corporate_actions": [
    {"symbol": "RELIANCE", "action_type": "DIVIDEND", "ex_date": "2026-07-10",
     "payload": {"amount": 1}}
  ],
  "business_classifications": [
    {"symbol": "RELIANCE", "business_type": "NON_FINANCIAL",
     "effective_from": "2026-01-01", "methodology_version": "business-v1",
     "reason": "reviewed primary activities"}
  ],
  "fundamentals": [
    {"symbol": "RELIANCE", "period_end": "2026-03-31",
     "effective_from": "2026-07-10", "debt_to_assets": 0.2,
     "interest_income_ratio": 0.02}
  ]
}
```

`available_at` means the first timestamp at which the system could have known the
record. It is not the reporting period or exchange session. Record-level timestamps may
override the bundle timestamp. Missing debt or interest ratios produce an `UNKNOWN`,
non-tradeable classification. `business_type` is also required for tradeability. Missing
business classification fails closed; conventional lenders are excluded before ratio
screening, and insurers require specialist review.

Business classifications are independently versioned point-in-time records. They require
an effective date, first-known timestamp, methodology version, reason, and retained source
manifest. Current labels must never be backfilled into earlier backtest dates.

Import with:

```bash
python -m src.reliability.nse_acquire bhavcopy \
  --start 2024-07-01 --end 2024-07-31 --output data/reliability/raw
python -m src.reliability.backfill_audit data/reliability/raw/source-catalogue.jsonl \
  bhavcopy --start 2024-07-01 --end 2024-07-31
python -m src.reliability.backfill_config data/reliability/raw/source-catalogue.jsonl \
  --start 2024-07-01 --end 2024-07-31 --output config/nse-data-sources.json
python -m src.reliability.nse_filings --output data/reliability/raw actions \
  --start 2024-07-01 --end 2024-07-31
python -m src.reliability.nse_filings --output data/reliability/raw results --period Annual
python -m src.reliability.nse_filings --output data/reliability/raw results \
  --period Quarterly --start 2024-06-01 --end 2024-06-30
python -m src.reliability.nse_filings --output data/reliability/raw xbrl \
  --index data/reliability/raw/financial_results/YYYY/MM/financial-results-annual-YYYYMMDD.json \
  --facts-output data/reliability/raw/financial-facts-annual.json --limit 25
python -m src.reliability.nse_filings --output data/reliability/raw xbrl-manifest \
  --manifest data/reliability/raw/xbrl-manifest.json \
  --facts-output data/reliability/raw/financial-facts-batch.json
python -m src.reliability.nse_pipeline config/nse-data-sources.json
python -m src.reliability.importers data/reliability/bundle.json \
  --db results/reliability.db --ruleset-version aaoifi-v1
python -m src.reliability.activation --db results/reliability.db
```

Start from `config/nse-data-sources.example.json`. Source paths are resolved relative
to the configuration file. The pipeline writes both the normalized bundle and a quality
report; it exits non-zero when current membership, price, or fundamental coverage fails.

After the activation command returns successfully, set the GitHub repository variable
`BORO_RELIABILITY_MODE=shadow`. The scheduled briefing will then use the durable outbox;
it never falls back to direct Telegram delivery when readiness fails.

Source files must be retained outside the database under their original names. The
importer records their SHA-256 digest; changing source bytes creates a new manifest.
The acquisition command limits each run to 31 calendar days, skips weekends, accepts
explicit `--holiday YYYY-MM-DD` values, and rate-limits requests. It validates ZIP/GZIP
payloads before atomically retaining both archive and extracted files. HTTP 404/410 is
catalogued as `missing_report`; transport and validation failures are recorded as
`failed` and are never inferred to be exchange holidays. Use `--dry-run` to inspect URLs
before download and `--url-template` for an approved mirror or NSE naming change.

Historical walk-forward universes use exact-session symbols from retained EQ bhavcopy bars,
queried with `ReliabilityStore.tradable_universe(session_date, as_of)`. This avoids filtering
old tests through today's ticker list. It represents tradability, not the complete legal list
of suspended securities; listing and delisting history remains a separate required dataset.

Corporate-action and financial-result API responses are retained as canonical JSON with
their retrieval time. Actions without an exchange broadcast timestamp are not backdated.
XBRL downloads are restricted to the NSE archive host, reject unsafe XML, and require an
explicit limit of at most 100 documents per run. Missing accounting concepts remain null;
the halal classifier must treat them as `UNKNOWN`, not estimate them.

Corporate-equity membership requires an active `EQ` record with an `INE...01...` equity
ISIN. `INF` fund units use holdings-based screening and are excluded from this corporate
ratio contract. Filing discovery joins by symbol first and ISIN second, preserving the
source symbol when NSE has retroactively renamed an issuer.
