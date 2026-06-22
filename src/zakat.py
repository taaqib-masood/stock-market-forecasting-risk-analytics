"""
Zakat + dividend-purification ledger.

Current-portfolio computations with no backtest / survivorship dependence — the
durable, differentiated value of the project (almost nobody serves a live Zakat +
purification ledger on a Shariah-screened portfolio).

  - Zakat: 2.5% of zakatable wealth, if at/above nisab and a lunar year (hawl) has
    passed. Method 'full' (majority view) = on full market value; method 'gains'
    (a minority view) = on capital gains only.
  - Purification: the impure-income fraction (interest income %) of dividends
    received from 🟡 holdings, to be given to charity (not counted as your income).
"""
from typing import Optional

# Silver-based nisab in ₹ (~2026). Silver is used (lower threshold → more inclusive,
# the cautious choice). Update annually from the live silver price.
SILVER_NISAB_INR = 45_000


def zakat_due(
    zakatable_value: float,
    method: str = "full",
    cost_basis: float = 0.0,
    rate: float = 0.025,
    nisab: float = SILVER_NISAB_INR,
    hawl_complete: bool = True,
) -> dict:
    """
    Zakat on a stock portfolio.

    zakatable_value : current market value of the holdings (₹)
    method          : 'full' (2.5% of market value) | 'gains' (2.5% of gains)
    cost_basis      : total purchase cost (used only for 'gains')
    hawl_complete   : whether a lunar year has elapsed on the wealth
    """
    if method == "gains":
        base = max(0.0, zakatable_value - cost_basis)
    else:
        base = max(0.0, zakatable_value)

    below_nisab = zakatable_value < nisab
    payable = (not below_nisab) and hawl_complete
    return {
        "method": method,
        "base": round(base, 2),
        "rate": rate,
        "nisab": nisab,
        "below_nisab": below_nisab,
        "hawl_complete": hawl_complete,
        "zakat_due": round(base * rate, 2) if payable else 0.0,
    }


def purification_due(holdings: list) -> dict:
    """
    Impure-dividend purification.

    holdings : list of {"ticker", "dividends", "impure_pct"} where impure_pct is the
               company's interest-income ratio (from halal_screen). Returns the amount
               to give to charity per holding and in total.
    """
    rows, total = [], 0.0
    for h in holdings:
        pct = float(h.get("impure_pct") or 0.0)
        amt = round(float(h.get("dividends", 0.0)) * pct, 2)
        total += amt
        rows.append({"ticker": h.get("ticker"), "dividends": h.get("dividends", 0.0),
                     "impure_pct": pct, "purification": amt})
    return {"total_purification": round(total, 2), "by_holding": rows}


def purification_for_portfolio(holdings: list, cache: Optional[dict] = None) -> dict:
    """
    Auto-purification: for each holding {ticker, dividends}, look up the company's
    impure-income ratio from the fundamentals cache and compute the dividend amount to
    give to charity — no manual impure_pct needed.

    Tickers whose impure ratio is unknown are treated as 0 BUT surfaced in
    `unknown_tickers` (never silently assume an unscreened company is clean).
    """
    from src.fundamentals import get_fundamentals
    enriched, unknown = [], []
    for h in holdings:
        tkr = h["ticker"]
        f = get_fundamentals(tkr, cache=cache)
        impure = f.get("interest_income_ratio") if f else None
        if impure is None:
            unknown.append(tkr)
        enriched.append({"ticker": tkr, "dividends": h.get("dividends", 0.0),
                         "impure_pct": impure or 0.0})
    out = purification_due(enriched)
    out["unknown_tickers"] = unknown
    return out


def portfolio_zakat_report(holdings: list, method: str = "full", rate: float = 0.025,
                           nisab: float = SILVER_NISAB_INR, hawl_complete: bool = True,
                           cache: Optional[dict] = None) -> dict:
    """
    Full annual halal-wealth report for a portfolio: Zakat (on total market value or gains)
    + dividend purification (auto-looked-up from the fundamentals cache).

    holdings : [{ticker, market_value, dividends, cost_basis?}]
    """
    total_value = round(sum(float(h.get("market_value", 0.0)) for h in holdings), 2)
    total_cost = round(sum(float(h.get("cost_basis", 0.0)) for h in holdings), 2)
    zakat = zakat_due(total_value, method=method, cost_basis=total_cost,
                      rate=rate, nisab=nisab, hawl_complete=hawl_complete)
    purification = purification_for_portfolio(holdings, cache=cache)
    return {"portfolio_value": total_value, "zakat": zakat, "purification": purification}
