import numpy as np
import pandas as pd


# ── Regression errors ─────────────────────────────────────────────────────────

def mae(y_true, y_pred):
    return np.mean(np.abs(y_true - y_pred))


def rmse(y_true, y_pred):
    return np.sqrt(np.mean((y_true - y_pred) ** 2))


def directional_accuracy(y_true, y_pred):
    """% of time the predicted direction matches actual direction."""
    return np.mean(np.sign(y_true) == np.sign(y_pred))


# ── Risk / portfolio metrics ──────────────────────────────────────────────────

def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0, periods: int = 252) -> float:
    """Annualised Sharpe ratio."""
    excess = returns - risk_free_rate / periods
    if excess.std() == 0:
        return 0.0
    return float(excess.mean() / excess.std() * np.sqrt(periods))


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0, periods: int = 252) -> float:
    """Annualised Sortino ratio (penalises downside volatility only)."""
    excess = returns - risk_free_rate / periods
    downside_std = excess[excess < 0].std()
    if downside_std == 0:
        return 0.0
    return float(excess.mean() / downside_std * np.sqrt(periods))


def max_drawdown(equity_curve: pd.Series) -> float:
    """Maximum peak-to-trough decline as a negative fraction."""
    cummax = equity_curve.cummax()
    drawdown = (equity_curve - cummax) / cummax
    return float(drawdown.min())


def calmar_ratio(returns: pd.Series, periods: int = 252) -> float:
    """Annualised return / |max drawdown|."""
    equity = (1 + returns).cumprod()
    mdd = abs(max_drawdown(equity))
    if mdd == 0:
        return 0.0
    annual_return = float(returns.mean() * periods)
    return annual_return / mdd


def profit_factor(returns: pd.Series) -> float:
    """Gross profit / gross loss. > 1.5 is good, > 2.0 is excellent."""
    gains = returns[returns > 0].sum()
    losses = abs(returns[returns < 0].sum())
    if losses == 0:
        return np.inf
    return float(gains / losses)


def win_rate(returns: pd.Series) -> float:
    return float((returns > 0).mean())


def expected_value(returns: pd.Series) -> float:
    """Average return per trade."""
    return float(returns.mean())


def avg_win_loss_ratio(returns: pd.Series) -> float:
    """Average winning trade / average losing trade (absolute)."""
    wins  = returns[returns > 0]
    losses = returns[returns < 0]
    if losses.empty or wins.empty:
        return 0.0
    return float(wins.mean() / abs(losses.mean()))


def annual_return(returns: pd.Series, periods: int = 252) -> float:
    """Annualised return as a percentage."""
    if len(returns) == 0:
        return 0.0
    n_years = len(returns) / periods
    total = (1 + returns).prod()
    return float((total ** (1 / n_years) - 1) * 100)


def summarise(returns: pd.Series, label: str = "Strategy", capital: float = None) -> dict:
    """Return a full risk/performance summary dict."""
    equity = (1 + returns).cumprod()
    wins   = returns[returns > 0]
    losses = returns[returns < 0]
    return {
        "label"                    : label,
        "total_trades"             : len(returns),
        "win_rate_pct"             : round(win_rate(returns) * 100, 2),
        "avg_win_pct"              : round(float(wins.mean()  * 100) if not wins.empty  else 0, 4),
        "avg_loss_pct"             : round(float(losses.mean() * 100) if not losses.empty else 0, 4),
        "avg_win_loss_ratio"       : round(avg_win_loss_ratio(returns), 4),
        "profit_factor"            : round(profit_factor(returns), 4),
        "sharpe"                   : round(sharpe_ratio(returns), 4),
        "sortino"                  : round(sortino_ratio(returns), 4),
        "calmar"                   : round(calmar_ratio(returns), 4),
        "max_drawdown_pct"         : round(max_drawdown(equity) * 100, 2),
        "annual_return_pct"        : round(annual_return(returns), 2),
        "total_return_pct"         : round((equity.iloc[-1] - 1) * 100, 2),
        "avg_return_per_trade_pct" : round(expected_value(returns) * 100, 4),
    }
