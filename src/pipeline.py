"""
Main pipeline: data → features → train → ensemble → backtest → report
Run: python -m src.pipeline --ticker AAPL --years 5
"""
import argparse
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Optional

from src.data_provider import load_bars
from src.feature_engineering import add_features
from src.arima_model import ArimaModel
from src.tree_model import TreeModel
from src.lstm_model import LSTMModel
from src.ensemble import EnsembleModel
from src.risk_manager import RiskManager, backtest_with_risk
from src.metrics import summarise
import src.mlflow_tracker as tracker

warnings.filterwarnings("ignore")

FEATURE_COLS = [
    # Price returns
    "return_1d", "return_3d", "return_5d",
    "return_lag_1", "return_lag_2", "return_lag_3", "return_lag_5",
    # Trend
    "price_vs_sma20", "price_vs_sma50", "price_vs_sma200",
    "sma5_vs_sma20", "golden_cross", "sma200_slope",
    # Momentum
    "rsi_14", "rsi_7", "rsi_21",
    "macd", "macd_signal", "macd_hist",
    "roc_5", "roc_10", "roc_20", "williams_r",
    # Volatility
    "atr_pct", "volatility_20", "volatility_10", "volatility_5",
    "bb_width", "bb_pct_b",
    # Volume
    "volume_ratio", "volume_zscore", "obv", "mfi_14", "cmf",
    # Calendar
    "day_of_week", "month", "days_to_expiry", "holiday_proximity",
]

MARKET_COLS = ["spy_return", "spy_above_sma50", "vix_close", "vix_regime"]


def load_data(ticker: str, years: int) -> pd.DataFrame:
    df = load_bars(ticker, years=years)
    print(f"  Loaded {len(df)} bars for {ticker}")
    return df


def get_feature_cols(df: pd.DataFrame) -> list[str]:
    available_market = [c for c in MARKET_COLS if c in df.columns]
    return [c for c in FEATURE_COLS + available_market if c in df.columns]


def monte_carlo_backtest(
    trade_returns: np.ndarray,
    capital: float = 100_000,
    n_simulations: int = 1000,
    out_dir: Optional[Path] = None,
) -> dict:
    """
    Monte Carlo simulation: resample trade returns to estimate distribution
    of possible outcomes. Shows best/worst/median final equity.

    Returns plain-English stats beginner can understand.
    """
    if len(trade_returns) < 5:
        return {"error": "Not enough trades for Monte Carlo (need ≥5)"}

    np.random.seed(42)
    final_equities = []
    max_drawdowns  = []

    for _ in range(n_simulations):
        sample = np.random.choice(trade_returns, size=len(trade_returns), replace=True)
        equity = capital * np.cumprod(1 + sample)
        peak   = np.maximum.accumulate(equity)
        dd     = ((equity - peak) / peak).min()
        final_equities.append(equity[-1])
        max_drawdowns.append(dd * 100)

    final_equities = np.array(final_equities)
    max_drawdowns  = np.array(max_drawdowns)

    p5, p25, p50, p75, p95 = np.percentile(final_equities, [5, 25, 50, 75, 95])
    prob_profit = (final_equities > capital).mean() * 100
    avg_max_dd  = max_drawdowns.mean()

    result = {
        "n_simulations":      n_simulations,
        "starting_capital":   capital,
        "worst_case_5pct":    round(p5, 2),
        "bad_case_25pct":     round(p25, 2),
        "median_outcome":     round(p50, 2),
        "good_case_75pct":    round(p75, 2),
        "best_case_95pct":    round(p95, 2),
        "probability_profit": round(prob_profit, 1),
        "avg_max_drawdown_pct": round(avg_max_dd, 2),
        "plain_english": (
            f"Running {n_simulations} simulated versions of this strategy:\n"
            f"  • Chance of ending profitable: {prob_profit:.0f}%\n"
            f"  • Most likely final value (median): ₹{p50:,.0f}\n"
            f"  • Worst 5% of outcomes: ₹{p5:,.0f}\n"
            f"  • Best 5% of outcomes:  ₹{p95:,.0f}\n"
            f"  • Average max drawdown you'd experience: {avg_max_dd:.1f}%"
        ),
    }

    # Save chart
    if out_dir:
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        axes[0].hist(final_equities, bins=60, color="steelblue", alpha=0.8, edgecolor="white")
        axes[0].axvline(capital, color="red",    linestyle="--", linewidth=1.5, label=f"Start ₹{capital:,.0f}")
        axes[0].axvline(p50,    color="green",   linestyle="-",  linewidth=2,   label=f"Median ₹{p50:,.0f}")
        axes[0].axvline(p5,     color="orange",  linestyle=":",  linewidth=1.5, label=f"5th pct ₹{p5:,.0f}")
        axes[0].set_title(f"Monte Carlo — Final Equity Distribution ({n_simulations:,} runs)")
        axes[0].set_xlabel("Final Portfolio Value (₹)")
        axes[0].set_ylabel("Frequency")
        axes[0].legend(fontsize=8)
        axes[0].grid(alpha=0.3)

        axes[1].hist(max_drawdowns, bins=40, color="tomato", alpha=0.8, edgecolor="white")
        axes[1].axvline(avg_max_dd, color="black", linestyle="--", linewidth=2,
                        label=f"Avg DD {avg_max_dd:.1f}%")
        axes[1].set_title("Distribution of Max Drawdowns")
        axes[1].set_xlabel("Max Drawdown (%)")
        axes[1].set_ylabel("Frequency")
        axes[1].legend(fontsize=8)
        axes[1].grid(alpha=0.3)

        plt.tight_layout()
        mc_path = out_dir / "monte_carlo.png"
        plt.savefig(mc_path, dpi=150)
        plt.close()
        result["chart_saved"] = str(mc_path)

    return result


def walk_forward_split(df: pd.DataFrame, test_frac: float = 0.2):
    split = int(len(df) * (1 - test_frac))
    return df.iloc[:split], df.iloc[split:]


def run(ticker: str = "AAPL", years: int = 5, capital: float = 100_000,
        confidence_threshold: float = 0.62, use_lstm: bool = False):

    out_dir = Path("results")
    out_dir.mkdir(exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Stock: {ticker} | History: {years}yr | Capital: ${capital:,.0f}")
    print(f"{'='*60}\n")

    _mlflow_run = tracker.start_run(
        ticker=ticker,
        model_type="ensemble",
        params={"years": years, "confidence_threshold": confidence_threshold, "use_lstm": use_lstm},
    )
    _mlflow_run.__enter__()

    # ── 1. Data & Features ────────────────────────────────────────────────────
    print("[1/5] Downloading data and engineering features...")
    raw = load_data(ticker, years)
    df = add_features(raw, fetch_context=True)
    tracker.log_dataset_hash(df)
    feat_cols = get_feature_cols(df)
    X, y = df[feat_cols], df["target"]
    print(f"  Features: {len(feat_cols)}  |  Samples: {len(df)}")

    # ── 2. Walk-forward split ─────────────────────────────────────────────────
    print("\n[2/5] Splitting train / test (80/20 walk-forward)...")
    train_df, test_df = walk_forward_split(df)
    X_train, y_train = train_df[feat_cols], train_df["target"]
    X_test, y_test   = test_df[feat_cols],  test_df["target"]
    print(f"  Train: {len(train_df)}  |  Test: {len(test_df)}")

    # ── 3. Base models ────────────────────────────────────────────────────────
    print("\n[3/5] Training base models...")

    # ARIMA (directional signal only — trained on close prices)
    arima = ArimaModel()
    arima.fit(train_df["Close"])
    arima_proba_train = np.full(len(X_train), arima.signal())
    arima_proba_test  = np.full(len(X_test),  arima.signal())
    print("  ✓ ARIMA (auto-order)")

    # Tree model (LightGBM / RandomForest)
    tree = TreeModel(n_estimators=500)
    tree.fit(X_train, y_train)
    tree_proba_train = tree.predict_proba(X_train)
    tree_proba_test  = tree.predict_proba(X_test)
    tree_train_acc = (tree.predict(X_train) == y_train).mean()
    tree_test_acc  = (tree.predict(X_test)  == y_test).mean()
    print(f"  ✓ Tree  — train acc: {tree_train_acc:.2%}  test acc: {tree_test_acc:.2%}")
    tracker.log_model_artifact(tree.model if hasattr(tree, "model") else tree, "tree_model")
    tracker.log_feature_importance(tree.model if hasattr(tree, "model") else tree, feat_cols)

    # LSTM (optional — slow, skip by default for fast runs)
    if use_lstm:
        lstm = LSTMModel(lookback=20, units=64, epochs=50)
        lstm.fit(X_train, y_train)
        lstm_proba_full  = lstm.predict_proba(df[feat_cols])
        n_tr = len(X_train)
        lstm_proba_train = lstm_proba_full[:n_tr]
        lstm_proba_test  = lstm_proba_full[n_tr:]
        lstm_test_acc = ((lstm_proba_test >= 0.5).astype(int) == y_test.values).mean()
        print(f"  ✓ LSTM  — test acc: {lstm_test_acc:.2%}")
    else:
        print("  ⚠ LSTM skipped (pass --lstm to enable)")
        lstm_proba_train = tree_proba_train  # placeholder
        lstm_proba_test  = tree_proba_test

    # ── 4. Meta-learner (stacking ensemble) ──────────────────────────────────
    print("\n[4/5] Training ensemble meta-learner...")
    ensemble = EnsembleModel(confidence_threshold=confidence_threshold)
    base_train = {"arima": arima_proba_train, "tree": tree_proba_train, "lstm": lstm_proba_train}
    base_test  = {"arima": arima_proba_test,  "tree": tree_proba_test,  "lstm": lstm_proba_test}
    ensemble.fit(base_train, y_train.values)

    signals_df = ensemble.signals(base_test)
    ensemble_preds = signals_df["signal"].values
    ensemble_conf  = signals_df["confidence"].values

    ensemble_acc = (
        (ensemble_preds[ensemble_preds != 0] == y_test.values[ensemble_preds != 0]).mean()
        if (ensemble_preds != 0).sum() > 0 else 0.0
    )
    filtered_trades = (ensemble_preds != 0).sum()
    print(f"  ✓ Ensemble — filtered signals: {filtered_trades}/{len(y_test)}")
    print(f"  ✓ Ensemble — directional accuracy on signals: {ensemble_acc:.2%}")

    # ── 5. Risk-managed backtest ──────────────────────────────────────────────
    print("\n[5/5] Running risk-managed backtest...")
    test_prices = test_df["Close"].squeeze()
    test_atrs   = test_df["atr_14"].squeeze()
    test_vix    = test_df["vix_close"].squeeze() if "vix_close" in test_df.columns else None

    sig_series   = pd.Series(ensemble_preds,  index=test_df.index)
    conf_series  = pd.Series(ensemble_conf,   index=test_df.index)

    trade_log = backtest_with_risk(
        prices=test_prices,
        signals=sig_series,
        confidences=conf_series,
        atrs=test_atrs,
        vix=test_vix,
        capital=capital,
        slippage_pct=0.001,          # 0.1% per fill
        commission_per_share=0.005,  # $0.005/share (IBKR)
        max_risk_pct=0.02,
        atr_multiplier=2.0,
        min_rr=2.0,
        max_position_pct=0.05,
        max_consecutive_losses=3,
    )

    # ── Results ───────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  RESULTS")
    print("="*60)

    if trade_log.empty:
        print("  No trades passed the risk filter. Lower confidence_threshold or check data.")
    else:
        trade_returns = trade_log["pnl"] / capital
        summary = summarise(trade_returns, label=f"{ticker} Ensemble+Risk")
        total_costs = trade_log["commission"].sum() + trade_log["slippage_cost"].sum()

        print(f"""
┌─────────────────────────────────────────────────────┐
│  PERFORMANCE REPORT — {ticker:<5}  (after costs)       │
├──────────────────────────────────┬──────────────────┤
│  Total Trades                    │ {summary['total_trades']:<16} │
│  Win Rate                        │ {summary['win_rate_pct']:<15.2f}% │
│  Avg Win                         │ {summary['avg_win_pct']:<15.4f}% │
│  Avg Loss                        │ {summary['avg_loss_pct']:<15.4f}% │
│  Avg Win / Avg Loss              │ {summary['avg_win_loss_ratio']:<16.2f} │
│  Profit Factor                   │ {summary['profit_factor']:<16.2f} │
├──────────────────────────────────┼──────────────────┤
│  Sharpe Ratio  (annualised)      │ {summary['sharpe']:<16.2f} │
│  Sortino Ratio (annualised)      │ {summary['sortino']:<16.2f} │
│  Calmar Ratio                    │ {summary['calmar']:<16.2f} │
│  Max Drawdown                    │ {summary['max_drawdown_pct']:<15.2f}% │
│  Annual Return                   │ {summary['annual_return_pct']:<15.2f}% │
│  Total Return                    │ {summary['total_return_pct']:<15.2f}% │
├──────────────────────────────────┼──────────────────┤
│  Slippage (0.1%) + Commission    │ ${total_costs:<15.2f} │
│  Avg Return / Trade              │ {summary['avg_return_per_trade_pct']:<15.4f}% │
└──────────────────────────────────┴──────────────────┘""")
        tracker.log_metrics({
            "sharpe_ratio": summary["sharpe"],
            "win_rate": summary["win_rate_pct"] / 100,
            "profit_factor": summary["profit_factor"],
            "max_drawdown": summary["max_drawdown_pct"] / 100,
            "annual_return": summary["annual_return_pct"] / 100,
            "total_trades": summary["total_trades"],
            "accuracy": ensemble_acc,
        })

        # ── Monte Carlo simulation ────────────────────────────────────────────
        trade_rets = (trade_log["pnl"] / capital).values
        mc = monte_carlo_backtest(trade_rets, capital=capital, n_simulations=1000, out_dir=out_dir)
        if "error" not in mc:
            print(f"\n  Monte Carlo ({mc['n_simulations']:,} simulations):")
            print(f"    {mc['plain_english']}")
            if "chart_saved" in mc:
                print(f"  Monte Carlo chart → {mc['chart_saved']}")

        print(f"\n  Tree Feature Importance (top 10):")
        top10 = tree.feature_importance().head(10)
        for feat, imp in top10.items():
            print(f"    {feat:<30} {imp:.4f}")

        # ── Save trade log ────────────────────────────────────────────────────
        log_path = out_dir / f"{ticker}_trade_log.csv"
        trade_log.to_csv(log_path, index=False)
        print(f"\n  Trade log saved → {log_path}")

        # ── Equity curve plot ─────────────────────────────────────────────────
        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=False)

        axes[0].plot(trade_log["equity"], marker="o", markersize=3, linewidth=1.5, color="steelblue")
        axes[0].axhline(capital, color="gray", linestyle="--", linewidth=0.8, label="Starting capital")
        axes[0].set_title(f"{ticker} — Equity Curve (Risk-Managed Ensemble)")
        axes[0].set_ylabel("Portfolio Value ($)")
        axes[0].legend()
        axes[0].grid(alpha=0.3)

        colors = ["green" if p > 0 else "red" for p in trade_log["pnl"]]
        axes[1].bar(range(len(trade_log)), trade_log["pnl"], color=colors, alpha=0.7)
        axes[1].axhline(0, color="black", linewidth=0.8)
        axes[1].set_title("Per-Trade P&L")
        axes[1].set_ylabel("P&L ($)")
        axes[1].set_xlabel("Trade #")
        axes[1].grid(alpha=0.3)

        plt.tight_layout()
        plot_path = out_dir / f"{ticker}_equity_curve.png"
        plt.savefig(plot_path, dpi=150)
        plt.close()
        print(f"  Equity curve saved → {plot_path}")

    print("\n" + "="*60 + "\n")
    _mlflow_run.__exit__(None, None, None)
    return trade_log


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker",    default="AAPL",    help="Stock ticker symbol")
    parser.add_argument("--years",     default=5, type=int, help="Years of history")
    parser.add_argument("--capital",   default=100_000, type=float, help="Starting capital")
    parser.add_argument("--threshold", default=0.62, type=float, help="Confidence threshold (0.5-1.0)")
    parser.add_argument("--lstm",      action="store_true", help="Enable LSTM model (slow)")
    args = parser.parse_args()

    run(
        ticker=args.ticker,
        years=args.years,
        capital=args.capital,
        confidence_threshold=args.threshold,
        use_lstm=args.lstm,
    )
