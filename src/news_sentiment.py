"""
UPGRADE 1: News Sentiment Analysis using FinBERT

Fetches headlines from Yahoo Finance RSS, Google News RSS, and Reddit,
runs them through FinBERT, and returns aggregated sentiment features.
Results are cached for 1 hour to avoid rate limits.
"""

import time
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional
import feedparser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory cache: { cache_key: (timestamp, result) }
# ---------------------------------------------------------------------------
_CACHE: dict = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour


def _cache_key(ticker: str) -> str:
    return hashlib.md5(ticker.upper().encode()).hexdigest()


def _from_cache(ticker: str) -> Optional[dict]:
    key = _cache_key(ticker)
    if key in _CACHE:
        ts, result = _CACHE[key]
        if time.time() - ts < _CACHE_TTL_SECONDS:
            return result
    return None


def _to_cache(ticker: str, result: dict):
    _CACHE[_cache_key(ticker)] = (time.time(), result)


# ---------------------------------------------------------------------------
# Headline fetchers
# ---------------------------------------------------------------------------

def _fetch_yahoo_headlines(ticker: str) -> list[str]:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    try:
        feed = feedparser.parse(url)
        return [e.title for e in feed.entries[:20]]
    except Exception as e:
        logger.warning("Yahoo RSS fetch failed for %s: %s", ticker, e)
        return []


def _fetch_google_news_headlines(ticker: str, company_name: str = "") -> list[str]:
    query = company_name if company_name else ticker
    url = f"https://news.google.com/rss/search?q={query}+stock&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(url)
        return [e.title for e in feed.entries[:20]]
    except Exception as e:
        logger.warning("Google News RSS fetch failed for %s: %s", ticker, e)
        return []


def _fetch_reddit_headlines(ticker: str) -> list[str]:
    """
    Uses Pushshift/Reddit RSS (no auth required for basic RSS).
    Falls back to r/stocks and r/wallstreetbets subreddit search RSS.
    """
    headlines = []
    for sub in ["wallstreetbets", "stocks", "investing"]:
        url = f"https://www.reddit.com/r/{sub}/search.rss?q={ticker}&restrict_sr=1&sort=new&limit=10"
        try:
            feed = feedparser.parse(url)
            headlines.extend([e.title for e in feed.entries[:10]])
        except Exception as e:
            logger.warning("Reddit RSS fetch failed for %s/%s: %s", sub, ticker, e)
    return headlines


# ---------------------------------------------------------------------------
# FinBERT sentiment analysis
# ---------------------------------------------------------------------------

def _load_finbert():
    """Lazily load FinBERT pipeline (cached at module level after first load)."""
    global _FINBERT_PIPELINE
    if _FINBERT_PIPELINE is not None:
        return _FINBERT_PIPELINE
    try:
        from transformers import pipeline
        _FINBERT_PIPELINE = pipeline(
            "text-classification",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert",
            top_k=None,          # return all three label scores
            device=-1,           # CPU; set to 0 for GPU
            truncation=True,
            max_length=512,
        )
        logger.info("FinBERT loaded successfully.")
    except ImportError:
        logger.error("transformers not installed. Run: pip install transformers torch")
        _FINBERT_PIPELINE = None
    return _FINBERT_PIPELINE


_FINBERT_PIPELINE = None


def _analyze_sentiment(headlines: list[str]) -> dict:
    """
    Run FinBERT on up to 50 headlines and aggregate scores.

    Returns:
        sentiment_score  : weighted average in [-1, +1]
        bullish_ratio    : fraction of headlines classified positive
        label_counts     : {"positive": int, "negative": int, "neutral": int}
    """
    if not headlines:
        return {"sentiment_score": 0.0, "bullish_ratio": 0.0, "label_counts": {}}

    pipe = _load_finbert()
    if pipe is None:
        return {"sentiment_score": 0.0, "bullish_ratio": 0.0, "label_counts": {}}

    label_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
    weighted_scores = []
    label_counts = {"positive": 0, "negative": 0, "neutral": 0}

    batch = headlines[:50]
    try:
        results = pipe(batch)
        for result in results:
            # result is a list of dicts: [{"label": "positive", "score": 0.9}, ...]
            if isinstance(result, list):
                top = max(result, key=lambda x: x["score"])
            else:
                top = result
            label = top["label"].lower()
            score_val = top["score"] * label_map.get(label, 0.0)
            weighted_scores.append(score_val)
            if label in label_counts:
                label_counts[label] += 1
    except Exception as e:
        logger.warning("FinBERT inference failed: %s", e)
        return {"sentiment_score": 0.0, "bullish_ratio": 0.0, "label_counts": label_counts}

    n = len(weighted_scores)
    sentiment_score = sum(weighted_scores) / n if n > 0 else 0.0
    bullish_ratio = label_counts["positive"] / n if n > 0 else 0.0

    return {
        "sentiment_score": round(sentiment_score, 4),
        "bullish_ratio": round(bullish_ratio, 4),
        "label_counts": label_counts,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_news_sentiment(ticker: str, company_name: str = "") -> dict:
    """
    Fetch and analyze news sentiment for a given stock ticker.

    Parameters
    ----------
    ticker       : e.g. "RELIANCE", "AAPL"
    company_name : optional full name for better Google News results

    Returns
    -------
    {
        "ticker"            : str,
        "sentiment_score"   : float,   # -1 (bearish) to +1 (bullish)
        "bullish_ratio"     : float,   # 0-1
        "news_volume"       : int,     # total headlines collected
        "top_5_headlines"   : list[str],
        "label_counts"      : dict,
        "cached"            : bool,
        "fetched_at"        : str,     # ISO timestamp
    }
    """
    cached = _from_cache(ticker)
    if cached:
        cached["cached"] = True
        return cached

    # Gather headlines from all sources
    yahoo = _fetch_yahoo_headlines(ticker)
    google = _fetch_google_news_headlines(ticker, company_name)
    reddit = _fetch_reddit_headlines(ticker)

    all_headlines = yahoo + google + reddit
    # De-duplicate while preserving order
    seen = set()
    unique_headlines = []
    for h in all_headlines:
        if h not in seen:
            seen.add(h)
            unique_headlines.append(h)

    sentiment = _analyze_sentiment(unique_headlines)

    result = {
        "ticker": ticker.upper(),
        "sentiment_score": sentiment["sentiment_score"],
        "bullish_ratio": sentiment["bullish_ratio"],
        "news_volume": len(unique_headlines),
        "top_5_headlines": unique_headlines[:5],
        "label_counts": sentiment["label_counts"],
        "cached": False,
        "fetched_at": datetime.utcnow().isoformat(),
    }

    _to_cache(ticker, result)
    return result


# ---------------------------------------------------------------------------
# Feature engineering helpers (called from feature_engineering.py)
# ---------------------------------------------------------------------------

def get_sentiment_features(ticker: str, company_name: str = "") -> dict:
    """
    Returns a flat dict of features ready for ML model ingestion.

    Features:
        sentiment_score     : current sentiment score (-1 to +1)
        sentiment_volume    : normalised news volume (log scale)
        sentiment_momentum  : placeholder — extend with historical snapshots
    """
    import math
    data = get_news_sentiment(ticker, company_name)
    score = data["sentiment_score"]
    volume = data["news_volume"]

    return {
        "sentiment_score": score,
        "sentiment_volume": round(math.log1p(volume), 4),
        # Momentum requires historical snapshots; initialised to 0
        "sentiment_momentum": 0.0,
    }


if __name__ == "__main__":
    import json
    result = get_news_sentiment("AAPL", "Apple")
    print(json.dumps(result, indent=2))
