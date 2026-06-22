"""
Quarterly fundamentals refresh (decoupled from the trading runtime).

WHY decoupled: Bharat-sm-data pulls pandas 3.0 / numpy 2.4, which would break the
trading venv. So this job runs in a SEPARATE venv and writes a stable JSON cache that
the trading code reads via src.fundamentals — the fragile scraping + heavy deps never
touch the live path. Source is Tickertape (a JSON API — stable, no HTML scraping / 403s).

SETUP (one-time, isolated venv):
    python3.14 -m venv .venv-fundamentals
    .venv-fundamentals/bin/pip install Bharat-sm-data

RUN (quarterly):
    .venv-fundamentals/bin/python scripts/refresh_fundamentals.py          # full watchlist
    .venv-fundamentals/bin/python scripts/refresh_fundamentals.py 5        # first 5 (test)

Resilient: rate-limited, retried with backoff, and PRESERVES existing cache entries on
per-ticker failure (a broken fetch never wipes good data).
"""
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.watchlist import DEFAULT_SCAN  # pure-python, safe to import in any venv

CACHE = ROOT / "data" / "fundamentals_cache.json"
SLEEP = 1.5  # be polite to the API


def _num(x):
    try:
        f = float(x)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _retry(fn, *a, tries=3, **k):
    for i in range(tries):
        try:
            return fn(*a, **k)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def fetch_one(t, ticker: str) -> dict:
    sid, _ = _retry(t.get_ticker, ticker)
    bs = _retry(t.get_balance_sheet_data, sid, num_time_periods=8)
    inc = _retry(t.get_income_data, sid, time_horizon="annual", num_time_periods=8)
    inc_by_period = {row.get("displayPeriod"): row for _, row in inc.iterrows()}

    history = []
    for _, b in bs.iterrows():
        period = b.get("displayPeriod")
        debt, assets = _num(b.get("balTdeb")), _num(b.get("balTota"))
        ir = inc_by_period.get(period, {})
        rev = _num(ir.get("incTrev")) if len(ir) else None
        ioi = _num(ir.get("incIoi")) if len(ir) else None   # interest + other income (conservative proxy)
        dta = round(debt / assets, 4) if (debt is not None and assets) else None
        iir = round(abs(ioi) / rev, 4) if (ioi is not None and rev) else None
        history.append({
            "period": period, "debt": debt, "assets": assets, "revenue": rev,
            "interest_other_income": ioi, "debt_to_assets": dta, "interest_income_ratio": iir,
        })

    latest = history[-1] if history else {}
    return {
        "fetched_at": time.strftime("%Y-%m-%d"),
        "source": "tickertape",
        "periods": [h["period"] for h in history],
        "latest": {"debt_to_assets": latest.get("debt_to_assets"),
                   "interest_income_ratio": latest.get("interest_income_ratio")},
        "history": history,
    }


def main(limit=None):
    from Fundamentals import Tickertape
    t = Tickertape()
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    tickers = DEFAULT_SCAN[:limit] if limit else DEFAULT_SCAN

    ok = fail = 0
    for i, tk in enumerate(tickers, 1):
        try:
            cache[tk] = fetch_one(t, tk)
            ok += 1
            lt = cache[tk]["latest"]
            print(f"[{i}/{len(tickers)}] {tk:12} OK   d/a={lt['debt_to_assets']}  int%={lt['interest_income_ratio']}")
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(tickers)}] {tk:12} FAIL {type(e).__name__} (kept old cache)")
        time.sleep(SLEEP)

    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2))
    print(f"\nDone. ok={ok} fail={fail}. Cache -> {CACHE}")


if __name__ == "__main__":
    main(limit=int(sys.argv[1]) if len(sys.argv) > 1 else None)
