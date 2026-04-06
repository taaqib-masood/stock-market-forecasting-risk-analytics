"""
NSE Halal Watchlist — Shariah-compliant stocks only.
Expanded to ~200 stocks across Nifty, Next50, Midcap, Smallcap & Sectoral.

Screening criteria (AAOIFI / NSE Shariah Index standards):
  ✅ ALLOWED  : Technology, Pharma, Healthcare, Manufacturing, Telecom,
                Infrastructure, Energy (non-speculative), FMCG (non-alcohol),
                Retail, Logistics, Chemicals, Diagnostics, Consumer Durables
  ❌ EXCLUDED : Banks & interest-based lenders (riba), Insurance (gharar),
                NBFCs with primary lending business, Alcohol, Tobacco,
                Gambling, Weapons/Defence (offensive), Adult entertainment
  📏 DEBT RULE: Debt-to-Assets ideally < 33% (AAOIFI standard)

Halal trading rules enforced in code:
  • BUY signals only — no short selling
  • No margin / leverage trading
  • Position sizing via Fractional Kelly (risk-managed)
"""

# ── Nifty 50 halal subset (34 stocks) ────────────────────────────────────────
HALAL_NIFTY = [
    # Technology
    "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM",
    # Telecom / Conglomerate
    "BHARTIARTL", "RELIANCE",
    # Auto & Manufacturing
    "MARUTI", "TVSMOTOR", "M&M", "EICHERMOT", "HEROMOTOCO",
    # Pharma & Healthcare
    "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP",
    # FMCG (non-alcohol/tobacco)
    "HINDUNILVR", "NESTLEIND", "TATACONSUM", "BRITANNIA",
    # Infrastructure & Capital Goods
    "LT", "ULTRACEMCO", "GRASIM", "ADANIPORTS", "BEL",
    # Metals & Mining
    "TATASTEEL", "JSWSTEEL", "HINDALCO",
    # Energy & Utilities
    "NTPC", "POWERGRID", "ONGC", "BPCL", "COALINDIA",
    # Retail / Consumer
    "TITAN", "TRENT",
]

# ── Nifty Next 50 halal subset (44 stocks) ───────────────────────────────────
HALAL_NEXT_50 = [
    # IT & Software
    "MPHASIS", "PERSISTENT", "COFORGE", "LTTS", "LTIM",
    # Pharma & Healthcare
    "AUROPHARMA", "TORNTPHARM", "LUPIN", "ALKEM",
    "LALPATHLAB", "MAXHEALTH", "METROPOLIS", "ZYDUSLIFE",
    # Auto & Auto-ancillary
    "BAJAJ-AUTO", "MOTHERSON", "ENDURANCE", "ESCORTS",
    "CEATLTD", "TIINDIA", "ASHOKLEY",
    # FMCG & Consumer
    "MARICO", "DABUR", "COLPAL", "EMAMILTD", "GODREJCP",
    # Infrastructure & Capital Goods
    "AMBUJACEM", "SIEMENS", "HAVELLS", "CROMPTON", "ABB",
    "THERMAX", "CUMMINSIND",
    # Real Estate (asset-backed, low debt)
    "OBEROIRLTY", "PRESTIGE", "DLF",
    # Energy & Utilities
    "TATAPOWER", "TORNTPOWER", "GAIL", "IGL", "ATGL", "PETRONET",
    # Logistics & Transport
    "IRCTC", "INDIGO", "DELHIVERY", "CONCOR",
    # Retail & Consumer
    "DMART", "ASIANPAINT",
    # Paints & Industrials
    "PIDILITIND", "BERGEPAINT",
]

# ── Halal Midcap (50 stocks) ─────────────────────────────────────────────────
HALAL_MIDCAP = [
    # IT & Software
    "KPITTECH", "OFSS", "TATAELXSI", "CYIENT", "HAPPSTMNDS",
    "BIRLASOFT", "MASTEK", "RATEGAIN", "INTELLECT",
    # Pharma & Diagnostics
    "NATCOPHARM", "LAURUSLABS", "GLAXO", "BIOCON",
    "ABBOTINDIA", "AJANTPHARM", "IPCALAB", "GRANULES",
    "ERIS", "SUDARSCHEM",
    # Auto & Components
    "FORCEMOT", "EXIDEIND", "MINDAIND", "SUPRAJIT", "SWARAJENG",
    # FMCG & Consumer
    "EIDPARRY", "FINEORG", "BIKAJI", "HONASA",
    # Infrastructure & Capital Goods
    "HUDCO", "NBCC", "APLAPOLLO", "JKCEMENT",
    "CENTURYTEX", "GRINDWELL", "KALPATPOWER", "KEC",
    "RITES", "IRFC",
    # Metals & Mining
    "GPIL", "NMDC", "MOIL",
    # Energy
    "MRPL", "CHENNPETRO", "GSPL", "NLCINDIA", "SJVN", "NHPC",
    # Chemicals
    "DEEPAKNTR", "CLEAN", "NOCIL", "GALAXYSURF",
    # Logistics
    "AEGISLOG", "BLUEDART",
    # Retail
    "METROBRAND", "PAGEIND", "VEDANT",
]

# ── Halal Smallcap additions (30 stocks) ─────────────────────────────────────
HALAL_SMALLCAP = [
    # IT Niche
    "NIITLTD", "XCHANGING", "ZENSAR", "HEXAWARE",
    # Pharma Niche
    "GLENMARK", "FDC", "NEULANDLAB", "JBCHEPHARM",
    # Auto Niche
    "GREENPANEL", "Gabriel", "SUNDRMFAST",
    # FMCG Niche
    "CCL", "ZYDUSWELL", "JYOTHYLAB",
    # Infrastructure Niche
    "ENGINERSIN", "RAILTEL", "HGINFRA", "PNC",
    # Energy Niche
    "MAHANGAS", "HINDPETRO", "BPCL",
    # Chemicals
    "GNFC", "TATACHEM",
    # Consumer Durables
    "VGUARD", "POLYCAB", "KEI", "FINOLEX",
    # Diagnostics
    "THYROCARE", "VIJAYADIAG",
    # Logistics
    "TCI", "MAHLOG",
]

# ── Sectoral / Thematic halal lists ──────────────────────────────────────────

# IT / Digital India
HALAL_IT = [
    "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM", "MPHASIS",
    "PERSISTENT", "COFORGE", "LTTS", "KPITTECH", "TATAELXSI", "OFSS",
    "CYIENT", "HAPPSTMNDS", "BIRLASOFT", "MASTEK", "INTELLECT",
    "RATEGAIN", "ZENSAR",
]

# Pharma & Healthcare (India is global pharma hub)
HALAL_PHARMA = [
    "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "AUROPHARMA",
    "TORNTPHARM", "LUPIN", "ALKEM", "ZYDUSLIFE", "BIOCON",
    "ABBOTINDIA", "AJANTPHARM", "IPCALAB", "GRANULES", "NATCOPHARM",
    "LAURUSLABS", "GLAXO", "ERIS", "GLENMARK", "FDC",
    "APOLLOHOSP", "MAXHEALTH", "METROPOLIS", "LALPATHLAB",
]

# Green Energy / Clean India
HALAL_GREEN_ENERGY = [
    "NTPC", "POWERGRID", "TATAPOWER", "TORNTPOWER", "SJVN",
    "NHPC", "ADANIGREEN", "GREENKO", "INOXWIND", "SUZLON",
    "WEBSOL", "WAAREE",
]

# Consumer / FMCG
HALAL_CONSUMER = [
    "HINDUNILVR", "NESTLEIND", "TATACONSUM", "BRITANNIA", "MARICO",
    "DABUR", "COLPAL", "EMAMILTD", "GODREJCP", "BIKAJI", "HONASA",
    "JYOTHYLAB", "ZYDUSWELL", "EIDPARRY",
]

# Infrastructure & Capital Goods
HALAL_INFRA = [
    "LT", "SIEMENS", "ABB", "HAVELLS", "THERMAX", "CUMMINSIND",
    "BEL", "APLAPOLLO", "KEC", "KALPATPOWER", "GRINDWELL",
    "ULTRACEMCO", "AMBUJACEM", "JKCEMENT", "NBCC", "RITES",
    "IRFC", "ENGINERSIN", "RAILTEL", "HGINFRA", "PNC",
]

# ── Scan lists ────────────────────────────────────────────────────────────────

# Fast daily scan (~75 stocks, large-cap focus)
DEFAULT_SCAN = HALAL_NIFTY + HALAL_NEXT_50

# Full scan (~165 stocks, Nifty + Next50 + Midcap)
EXTENDED_SCAN = list(dict.fromkeys(HALAL_NIFTY + HALAL_NEXT_50 + HALAL_MIDCAP))

# Deep weekend scan (~195 stocks, all tiers)
DEEP_SCAN = list(dict.fromkeys(
    HALAL_NIFTY + HALAL_NEXT_50 + HALAL_MIDCAP + HALAL_SMALLCAP
))

# Thematic baskets (for sector rotation analysis)
SECTOR_BASKETS = {
    "IT":           HALAL_IT,
    "Pharma":       HALAL_PHARMA,
    "GreenEnergy":  HALAL_GREEN_ENERGY,
    "Consumer":     HALAL_CONSUMER,
    "Infra":        HALAL_INFRA,
}

# ── Sector mapping (flat dict for scanner / sector rotation) ─────────────────
STOCK_SECTOR = {
    # Technology
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    "MPHASIS": "IT", "PERSISTENT": "IT", "COFORGE": "IT", "LTTS": "IT",
    "LTIM": "IT", "KPITTECH": "IT", "OFSS": "IT", "TATAELXSI": "IT",
    "CYIENT": "IT", "HAPPSTMNDS": "IT", "BIRLASOFT": "IT", "MASTEK": "IT",
    "RATEGAIN": "IT", "INTELLECT": "IT", "ZENSAR": "IT", "NIITLTD": "IT",
    "XCHANGING": "IT", "HEXAWARE": "IT",
    # Telecom
    "BHARTIARTL": "Telecom", "RELIANCE": "Telecom",
    # Auto & Components
    "MARUTI": "Auto", "TVSMOTOR": "Auto", "M&M": "Auto", "EICHERMOT": "Auto",
    "HEROMOTOCO": "Auto", "BAJAJ-AUTO": "Auto", "MOTHERSON": "Auto",
    "ENDURANCE": "Auto", "ESCORTS": "Auto", "CEATLTD": "Auto",
    "FORCEMOT": "Auto", "EXIDEIND": "Auto", "TIINDIA": "Auto",
    "ASHOKLEY": "Auto", "MINDAIND": "Auto", "SUPRAJIT": "Auto",
    "SWARAJENG": "Auto", "GABRIEL": "Auto", "SUNDRMFAST": "Auto",
    # Pharma & Healthcare
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma",
    "DIVISLAB": "Pharma", "APOLLOHOSP": "Pharma", "AUROPHARMA": "Pharma",
    "TORNTPHARM": "Pharma", "LUPIN": "Pharma", "ALKEM": "Pharma",
    "LALPATHLAB": "Pharma", "MAXHEALTH": "Pharma", "METROPOLIS": "Pharma",
    "NATCOPHARM": "Pharma", "LAURUSLABS": "Pharma", "GLAXO": "Pharma",
    "BIOCON": "Pharma", "ABBOTINDIA": "Pharma", "AJANTPHARM": "Pharma",
    "IPCALAB": "Pharma", "GRANULES": "Pharma", "ERIS": "Pharma",
    "ZYDUSLIFE": "Pharma", "GLENMARK": "Pharma", "FDC": "Pharma",
    "NEULANDLAB": "Pharma", "JBCHEPHARM": "Pharma", "THYROCARE": "Pharma",
    "VIJAYADIAG": "Pharma", "SUDARSCHEM": "Pharma",
    # FMCG & Consumer
    "HINDUNILVR": "FMCG", "NESTLEIND": "FMCG", "TATACONSUM": "FMCG",
    "BRITANNIA": "FMCG", "MARICO": "FMCG", "DABUR": "FMCG",
    "COLPAL": "FMCG", "EMAMILTD": "FMCG", "GODREJCP": "FMCG",
    "EIDPARRY": "FMCG", "BIKAJI": "FMCG", "HONASA": "FMCG",
    "JYOTHYLAB": "FMCG", "ZYDUSWELL": "FMCG", "CCL": "FMCG",
    # Infrastructure & Capital Goods
    "LT": "Infra", "ULTRACEMCO": "Infra", "GRASIM": "Infra", "BEL": "Infra",
    "AMBUJACEM": "Infra", "SIEMENS": "Infra", "HAVELLS": "Infra",
    "CROMPTON": "Infra", "HUDCO": "Infra", "NBCC": "Infra",
    "APLAPOLLO": "Infra", "JKCEMENT": "Infra", "CENTURYTEX": "Infra",
    "GRINDWELL": "Infra", "ABB": "Infra", "THERMAX": "Infra",
    "CUMMINSIND": "Infra", "KALPATPOWER": "Infra", "KEC": "Infra",
    "RITES": "Infra", "IRFC": "Infra", "ENGINERSIN": "Infra",
    "RAILTEL": "Infra", "HGINFRA": "Infra", "PNC": "Infra",
    # Metals & Mining
    "TATASTEEL": "Metal", "JSWSTEEL": "Metal", "HINDALCO": "Metal",
    "GPIL": "Metal", "GNFC": "Metal", "NMDC": "Metal", "MOIL": "Metal",
    "TATACHEM": "Metal",
    # Energy & Utilities
    "NTPC": "Energy", "POWERGRID": "Energy", "ONGC": "Energy",
    "BPCL": "Energy", "COALINDIA": "Energy", "TATAPOWER": "Energy",
    "TORNTPOWER": "Energy", "GAIL": "Energy", "IGL": "Energy",
    "ATGL": "Energy", "MRPL": "Energy", "CHENNPETRO": "Energy",
    "GSPL": "Energy", "NLCINDIA": "Energy", "SJVN": "Energy",
    "NHPC": "Energy", "PETRONET": "Energy", "HINDPETRO": "Energy",
    "MAHANGAS": "Energy", "ADANIGREEN": "Energy", "INOXWIND": "Energy",
    "SUZLON": "Energy", "WEBSOL": "Energy", "WAAREE": "Energy",
    # Retail & Consumer Brands
    "TITAN": "Retail", "TRENT": "Retail", "DMART": "Retail",
    "NYKAA": "Retail", "METROBRAND": "Retail", "PAGEIND": "Retail",
    "JUBLFOOD": "Retail", "VEDANT": "Retail",
    # Real Estate
    "ADANIENT": "RealEstate", "ADANIPORTS": "RealEstate",
    "OBEROIRLTY": "RealEstate", "PRESTIGE": "RealEstate", "DLF": "RealEstate",
    # Chemicals & Specialty
    "ASIANPAINT": "Chemical", "PIDILITIND": "Chemical", "BERGEPAINT": "Chemical",
    "FINEORG": "Chemical", "KAJARIACER": "Chemical", "DEEPAKNTR": "Chemical",
    "CLEAN": "Chemical", "NOCIL": "Chemical", "GALAXYSURF": "Chemical",
    # Logistics & Transport
    "IRCTC": "Logistics", "INDIGO": "Logistics", "DELHIVERY": "Logistics",
    "AEGISLOG": "Logistics", "CONCOR": "Logistics", "BLUEDART": "Logistics",
    "TCI": "Logistics", "MAHLOG": "Logistics",
    # Consumer Durables & Electricals
    "VGUARD": "ConsumerDurables", "POLYCAB": "ConsumerDurables",
    "KEI": "ConsumerDurables", "FINOLEX": "ConsumerDurables",
}

# ── NSE Shariah indices (reference) ──────────────────────────────────────────
# NSE maintains three official Shariah indices:
#   • NIFTY50 Shariah     — top 50 shariah-screened
#   • NIFTY Shariah 25    — top 25
#   • NIFTY500 Shariah    — broad 500
# Screening body: Taqwaa Advisory and Shariah Investment Solutions (TASIS)
# Standard: AAOIFI — Debt/Assets < 33%, interest income < 5% total revenue

# Legacy aliases kept for backward compatibility
HALAL_NIFTY50 = HALAL_NIFTY          # old name
DEFAULT_HALAL  = DEFAULT_SCAN         # old name


def nse(ticker: str) -> str:
    """Convert NSE ticker to yfinance format (append .NS)."""
    if ticker.endswith(".NS"):
        return ticker
    return f"{ticker}.NS"


def get_sector(ticker: str) -> str:
    """Return sector for a ticker, or 'Unknown'."""
    return STOCK_SECTOR.get(ticker.upper(), "Unknown")


def get_tickers_by_sector(sector: str) -> list:
    """Return all halal tickers in a given sector."""
    return [t for t, s in STOCK_SECTOR.items() if s == sector]
