"""
UPGRADE 3: AI-Powered Trade Explanations (SHAP + LLM)

Uses SHAP to find feature importance, then passes findings to
Groq (free tier) or a local Ollama/Llama 3 model to generate
plain-English trade explanations.
"""

import os
import logging
from typing import Any, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SHAP feature attribution
# ---------------------------------------------------------------------------

def _get_shap_values(
    model: Any,
    features: pd.Series | pd.DataFrame | dict,
    background_data: Optional[pd.DataFrame] = None,
) -> list[tuple[str, float]]:
    """
    Compute SHAP values for a single prediction.

    Returns sorted list of (feature_name, shap_value) tuples,
    highest absolute value first.
    """
    try:
        import shap
    except ImportError:
        logger.error("shap not installed. Run: pip install shap")
        return []

    if isinstance(features, dict):
        features = pd.Series(features)
    if isinstance(features, pd.Series):
        features = features.to_frame().T

    try:
        # Try TreeExplainer first (fast for tree-based models)
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(features)
        # For binary classifiers shap_values may be list[array]; take class-1
        if isinstance(shap_values, list):
            shap_values = shap_values[1]
        sv = shap_values[0]
    except Exception:
        # Fall back to KernelExplainer (model-agnostic, slower)
        if background_data is None:
            logger.warning("No background data for KernelExplainer; using zeros.")
            background_data = pd.DataFrame(
                np.zeros((1, features.shape[1])), columns=features.columns
            )
        try:
            explainer = shap.KernelExplainer(
                model.predict_proba, background_data.values
            )
            shap_values = explainer.shap_values(features.values, nsamples=100)
            if isinstance(shap_values, list):
                shap_values = shap_values[1]
            sv = shap_values[0]
        except Exception as e:
            logger.error("SHAP explainer failed: %s", e)
            return []

    names = features.columns.tolist()
    pairs = sorted(zip(names, sv.tolist()), key=lambda x: abs(x[1]), reverse=True)
    return pairs


# ---------------------------------------------------------------------------
# LLM explanation builders
# ---------------------------------------------------------------------------

def _build_prompt(
    ticker: str,
    signal: str,
    confidence: float,
    price: float,
    top_features: list[tuple[str, float]],
    macro_context: Optional[dict] = None,
    sentiment: Optional[dict] = None,
) -> str:
    feature_lines = "\n".join(
        f"  - {name}: SHAP contribution = {val:+.4f}"
        for name, val in top_features[:8]
    )
    macro_str = ""
    if macro_context:
        vix = macro_context.get("vix", "N/A")
        spread = macro_context.get("yield_spread", "N/A")
        macro_str = f"\nMacro context: VIX={vix}, Yield Curve Spread={spread}"

    sentiment_str = ""
    if sentiment:
        score = sentiment.get("sentiment_score", 0)
        vol = sentiment.get("news_volume", 0)
        sentiment_str = f"\nNews sentiment: score={score:+.2f}, volume={vol} headlines"

    return f"""You are a professional stock market analyst. Explain this trading signal clearly and concisely.

Stock: {ticker}
Signal: {signal}
Model confidence: {confidence:.1%}
Current price: ₹{price:.2f}
{macro_str}{sentiment_str}

Top feature contributions (SHAP values):
{feature_lines}

Provide:
1. A 2-3 sentence plain-English summary of WHY this signal was generated.
2. The top 2-3 bullish factors driving the signal.
3. The top 1-2 risk factors (if any bearish SHAP values exist).
4. A specific risk warning if VIX > 25 or yield curve is inverted.
5. A one-line actionable trade suggestion (entry price, stop-loss level).

Keep the tone professional. Do not use bullet points — write in sentences."""


def _call_groq(prompt: str, api_key: str) -> str:
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.3,
            max_tokens=400,
        )
        return response.choices[0].message.content.strip()
    except ImportError:
        logger.error("groq not installed. Run: pip install groq")
        return ""
    except Exception as e:
        logger.error("Groq API call failed: %s", e)
        return ""


def _call_ollama(prompt: str, model: str = "llama3") -> str:
    """Call a locally running Ollama instance."""
    try:
        import requests
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        logger.error("Ollama call failed: %s", e)
        return ""


def _fallback_explanation(
    ticker: str,
    signal: str,
    confidence: float,
    top_features_up: list[tuple[str, float]],
    top_features_down: list[tuple[str, float]],
) -> str:
    up_names = ", ".join(f[0] for f in top_features_up[:3])
    down_names = ", ".join(f[0] for f in top_features_down[:2])
    return (
        f"This {signal} signal for {ticker} (confidence {confidence:.1%}) is driven by "
        f"bullish factors: {up_names or 'none identified'}. "
        + (f"Bearish headwinds include: {down_names}." if down_names else "")
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def explain_trade(
    signal: str,
    features: pd.Series | pd.DataFrame | dict,
    model: Any,
    ticker: str,
    confidence: float = 0.0,
    price: float = 0.0,
    macro_context: Optional[dict] = None,
    sentiment: Optional[dict] = None,
    background_data: Optional[pd.DataFrame] = None,
    groq_api_key: Optional[str] = None,
    use_ollama: bool = False,
    ollama_model: str = "llama3",
) -> dict:
    """
    Generate an AI-powered explanation for a trade signal.

    Parameters
    ----------
    signal        : "BUY" | "SELL" | "HOLD"
    features      : feature dict/Series/DataFrame for the current bar
    model         : fitted sklearn-compatible model with predict_proba
    ticker        : stock symbol (e.g. "RELIANCE")
    confidence    : model confidence (0-1)
    price         : current market price
    macro_context : dict from macro_indicators.get_macro_indicators()
    sentiment     : dict from news_sentiment.get_news_sentiment()
    background_data: optional background dataset for KernelExplainer
    groq_api_key  : Groq API key (falls back to env var GROQ_API_KEY)
    use_ollama    : if True, use local Ollama instead of Groq
    ollama_model  : Ollama model name (default "llama3")

    Returns
    -------
    {
        "summary"           : str,
        "top_features_up"   : list[tuple[str, float]],
        "top_features_down" : list[tuple[str, float]],
        "risk_warning"      : str,
        "actionable_advice" : str,
    }
    """
    # --- SHAP attribution ---
    shap_pairs = _get_shap_values(model, features, background_data)
    top_features_up = [(n, v) for n, v in shap_pairs if v > 0][:5]
    top_features_down = [(n, v) for n, v in shap_pairs if v < 0][:3]

    # --- Risk warning from macro context ---
    risk_warning = ""
    if macro_context:
        vix = macro_context.get("vix")
        regime = macro_context.get("yield_curve_regime", "")
        if vix and vix > 25:
            risk_warning += f"VIX is elevated at {vix:.1f} — consider half position. "
        if regime == "inverted":
            risk_warning += "Yield curve is inverted — recession risk elevated. "
    if not risk_warning:
        risk_warning = "No major macro risk flags at this time."

    # --- Actionable advice (simple rule-based if LLM unavailable) ---
    if price > 0:
        stop_pct = 0.02  # 2% default stop
        entry = price
        stop = round(price * (1 - stop_pct) if signal == "BUY" else price * (1 + stop_pct), 2)
        actionable_advice = (
            f"Place {'limit' if signal == 'BUY' else 'sell'} order at ₹{entry:.2f}, "
            f"stop-loss at ₹{stop:.2f} ({stop_pct*100:.0f}% risk)."
        )
    else:
        actionable_advice = "Set stop-loss based on ATR before entering."

    # --- LLM summary ---
    api_key = groq_api_key or os.environ.get("GROQ_API_KEY")
    summary = ""

    if use_ollama:
        prompt = _build_prompt(ticker, signal, confidence, price, shap_pairs, macro_context, sentiment)
        summary = _call_ollama(prompt, ollama_model)
    elif api_key:
        prompt = _build_prompt(ticker, signal, confidence, price, shap_pairs, macro_context, sentiment)
        summary = _call_groq(prompt, api_key)

    if not summary:
        summary = _fallback_explanation(ticker, signal, confidence, top_features_up, top_features_down)

    return {
        "summary": summary,
        "top_features_up": top_features_up,
        "top_features_down": top_features_down,
        "risk_warning": risk_warning.strip(),
        "actionable_advice": actionable_advice,
    }


if __name__ == "__main__":
    # Minimal smoke test (no model required)
    result = explain_trade(
        signal="BUY",
        features={"RSI_14": 32, "MACD": 0.5, "VIX": 28},
        model=None,
        ticker="RELIANCE",
        confidence=0.74,
        price=1285.0,
    )
    for k, v in result.items():
        print(f"{k}: {v}")
