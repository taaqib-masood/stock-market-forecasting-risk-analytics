"""
NSE Halal Watchlist — Shariah-compliant stocks only.

Screening criteria applied:
  ✅ ALLOWED  : Technology, Pharma, Manufacturing, Telecom, Infrastructure,
                Energy (non-speculative), FMCG (non-alcohol), Retail, Logistics
  ❌ REMOVED  : Banks & interest-based NBFCs (riba), Insurance (gharar),
                Alcohol (MCDOWELL-N), Tobacco (ITC), Gambling, Weapons

Note: No short selling. Only BUY signals. No margin/leverage trading.
"""

# ── Halal Nifty 50 (banks/insurance/alcohol/tobacco removed) ─────────────────
HALAL_NIFTY = [
    # Technology
    "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM",
    # Telecom
    "BHARTIARTL", "RELIANCE",
    # Auto & Manufacturing
    "MARUTI", "TVSMOTOR", "M&M", "EICHERMOT", "HEROMOTOCO",
    # Pharma & Healthcare
    "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP",
    # FMCG (non-alcohol)
    "HINDUNILVR", "NESTLEIND", "TATACONSUM", "BRITANNIA",
    # Infrastructure & Capital Goods
    "LT", "ULTRACEMCO", "GRASIM", "ADANIPORTS", "BEL",
    # Metals & Mining
    "TATASTEEL", "JSWSTEEL", "HINDALCO",
    # Energy (non-speculative)
    "NTPC", "POWERGRID", "ONGC", "BPCL", "COALINDIA",
    # Conglomerate / Retail
    "ADANIENT", "TITAN", "ASIANPAINT", "TRENT",
]

# ── Halal Nifty Next 50 ───────────────────────────────────────────────────────
HALAL_NEXT_50 = [
    # Technology & IT Services
    "MPHASIS", "PERSISTENT", "COFORGE", "LTTS",
    # Pharma & Healthcare
    "AUROPHARMA", "TORNTPHARM", "LUPIN", "ALKEM", "LALPATHLAB", "MAXHEALTH",
    # Auto & Auto-ancillary
    "BAJAJ-AUTO", "MOTHERSON", "ENDURANCE", "ESCORTS", "CEATLTD",
    # FMCG & Consumer
    "MARICO", "DABUR", "COLPAL", "EMAMILTD", "GODREJCP",
    # Infrastructure & Construction
    "AMBUJACEM", "SIEMENS", "HAVELLS", "CROMPTON", "OBEROIRLTY", "PRESTIGE", "DLF",
    # Energy & Utilities
    "TATAPOWER", "TORNTPOWER", "GAIL", "IGL", "ATGL",
    # Logistics & Transport
    "IRCTC", "INDIGO", "DELHIVERY",
    # Retail & Consumer
    "DMART", "NYKAA", "TRENT",
    # Industrials
    "PIDILITIND", "BERGEPAINT", "KAJARIACER", "GRINDWELL",
]

# ── Halal Midcap ──────────────────────────────────────────────────────────────
HALAL_MIDCAP = [
    # Tech
    "KPITTECH", "HFCL", "OFSS",
    # Pharma
    "NATCOPHARM", "LAURUSLABS", "GLAXO",
    # Auto
    "FORCEMOT", "EXIDEIND",
    # FMCG
    "EIDPARRY", "FINEORG",
    # Infra / Energy
    "HUDCO", "NBCC", "NLCINDIA", "MRPL", "CHENNPETRO", "GNFC", "GSPL",
    # Industrials
    "APLAPOLLO", "GPIL", "JKCEMENT", "CENTURYTEX",
    # Retail / Consumer
    "METROBRAND", "PAGEIND", "JUBLFOOD",
    # Logistics
    "AEGISLOG", "CONCOR",
]

# ── Scan lists ────────────────────────────────────────────────────────────────

# Default — used by daily_briefing (fast, ~75 stocks)
DEFAULT_SCAN = HALAL_NIFTY + HALAL_NEXT_50

# Extended — used for weekend deep scans (~120 stocks)
EXTENDED_SCAN = HALAL_NIFTY + HALAL_NEXT_50 + HALAL_MIDCAP

# Sector mapping (halal stocks only)
STOCK_SECTOR = {
    # Technology
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    "MPHASIS": "IT", "PERSISTENT": "IT", "COFORGE": "IT", "LTTS": "IT", "KPITTECH": "IT",
    "OFSS": "IT", "HFCL": "IT",
    # Telecom
    "BHARTIARTL": "Telecom", "RELIANCE": "Telecom",
    # Auto
    "MARUTI": "Auto", "TVSMOTOR": "Auto", "M&M": "Auto", "EICHERMOT": "Auto",
    "HEROMOTOCO": "Auto", "BAJAJ-AUTO": "Auto", "MOTHERSON": "Auto",
    "ENDURANCE": "Auto", "ESCORTS": "Auto", "CEATLTD": "Auto", "FORCEMOT": "Auto",
    "EXIDEIND": "Auto",
    # Pharma
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma",
    "DIVISLAB": "Pharma", "APOLLOHOSP": "Pharma", "AUROPHARMA": "Pharma",
    "TORNTPHARM": "Pharma", "LUPIN": "Pharma", "ALKEM": "Pharma",
    "LALPATHLAB": "Pharma", "MAXHEALTH": "Pharma", "NATCOPHARM": "Pharma",
    "LAURUSLABS": "Pharma", "GLAXO": "Pharma",
    # FMCG
    "HINDUNILVR": "FMCG", "NESTLEIND": "FMCG", "TATACONSUM": "FMCG",
    "BRITANNIA": "FMCG", "MARICO": "FMCG", "DABUR": "FMCG", "COLPAL": "FMCG",
    "EMAMILTD": "FMCG", "GODREJCP": "FMCG", "EIDPARRY": "FMCG",
    # Infra & Capital Goods
    "LT": "Infra", "ULTRACEMCO": "Infra", "GRASIM": "Infra", "BEL": "Infra",
    "AMBUJACEM": "Infra", "SIEMENS": "Infra", "HAVELLS": "Infra",
    "CROMPTON": "Infra", "HUDCO": "Infra", "NBCC": "Infra", "APLAPOLLO": "Infra",
    "JKCEMENT": "Infra", "CENTURYTEX": "Infra", "GRINDWELL": "Infra",
    # Metals
    "TATASTEEL": "Metal", "JSWSTEEL": "Metal", "HINDALCO": "Metal",
    "GPIL": "Metal", "GNFC": "Metal",
    # Energy
    "NTPC": "Energy", "POWERGRID": "Energy", "ONGC": "Energy", "BPCL": "Energy",
    "COALINDIA": "Energy", "TATAPOWER": "Energy", "TORNTPOWER": "Energy",
    "GAIL": "Energy", "IGL": "Energy", "ATGL": "Energy", "MRPL": "Energy",
    "CHENNPETRO": "Energy", "GSPL": "Energy", "NLCINDIA": "Energy",
    # Retail & Consumer
    "TITAN": "Retail", "TRENT": "Retail", "DMART": "Retail", "NYKAA": "Retail",
    "METROBRAND": "Retail", "PAGEIND": "Retail", "JUBLFOOD": "Retail",
    # Real Estate
    "ADANIENT": "RealEstate", "ADANIPORTS": "RealEstate",
    "OBEROIRLTY": "RealEstate", "PRESTIGE": "RealEstate", "DLF": "RealEstate",
    # Paints & Chemicals
    "ASIANPAINT": "Chemical", "PIDILITIND": "Chemical", "BERGEPAINT": "Chemical",
    "FINEORG": "Chemical", "KAJARIACER": "Chemical",
    # Logistics
    "IRCTC": "Logistics", "INDIGO": "Logistics", "DELHIVERY": "Logistics",
    "AEGISLOG": "Logistics", "CONCOR": "Logistics",
}


def nse(ticker: str) -> str:
    """Convert NSE ticker to yfinance format."""
    return f"{ticker}.NS"
