"""
NSE Watchlist — Nifty 50 + Nifty Next 50
These are the most liquid, reliable stocks on NSE.
yfinance NSE suffix: append ".NS" to ticker.
"""

NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "BHARTIARTL", "ICICIBANK",
    "INFY", "SBIN", "HINDUNILVR", "ITC", "LT",
    "KOTAKBANK", "AXISBANK", "MARUTI", "SUNPHARMA", "BAJFINANCE",
    "HCLTECH", "TITAN", "ASIANPAINT", "ULTRACEMCO", "WIPRO",
    "NTPC", "POWERGRID", "NESTLEIND", "TVSMOTOR", "M&M",
    "TECHM", "INDUSINDBK", "TATASTEEL", "JSWSTEEL", "ADANIENT",
    "ONGC", "BPCL", "GRASIM", "HINDALCO", "DIVISLAB",
    "DRREDDY", "CIPLA", "APOLLOHOSP", "BAJAJFINSV", "EICHERMOT",
    "COALINDIA", "HDFCLIFE", "SBILIFE", "TRENT", "BEL",
    "SHRIRAMFIN", "HEROMOTOCO", "ADANIPORTS", "TATACONSUM", "BRITANNIA",
]

NIFTY_NEXT_50 = [
    "SIEMENS", "HAVELLS", "PIDILITIND", "MARICO", "DABUR",
    "BERGEPAINT", "COLPAL", "MCDOWELL-N", "GODREJCP", "AMBUJACEM",
    "BANKBARODA", "CANBK", "PNB", "IDFCFIRSTB", "FEDERALBNK",
    "MUTHOOTFIN", "CHOLAFIN", "BAJAJ-AUTO", "TVSMOTORS", "MOTHERSON",
    "AUROPHARMA", "TORNTPHARM", "LUPIN", "BIOCON", "ALKEM",
    "LTI", "MPHASIS", "PERSISTENT", "COFORGE", "LTTS",
    "IRCTC", "CONCOR", "DMART", "NYKAA", "POLICYBZR",
    "ZOMATO", "PAYTM", "VEDL", "SAIL", "NMDC",
    "GAIL", "IGL", "MGL", "TATAPOWER", "TORNTPOWER",
    "INDIGO", "SPICEJET", "OBEROIRLTY", "PRESTIGE", "DLF",
]

# Default scan list — top 30 most liquid for speed
DEFAULT_SCAN = NIFTY_50[:30]

def nse(ticker: str) -> str:
    """Convert NSE ticker to yfinance format."""
    return f"{ticker}.NS"
