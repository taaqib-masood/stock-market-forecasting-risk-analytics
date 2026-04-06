"""
UPGRADE 6: Model & Data Drift Detection

Monitors two types of drift:
  1. Data drift   — feature distributions shifting (KS test + PSI)
  2. Model drift  — rolling 30-trade accuracy falling below threshold

Sends Telegram alert via notify.py if drift is detected.
Recommends retraining when both types of drift are present.

CLI Usage:
    python -m src.drift_detector --ticker RELIANCE
    python -m src.drift_detector --ticker RELIANCE --ref-days 120 --live-days 30
"""

import argparse
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

# Thresholds
KS_P_THRESHOLD = 0.05       # KS p-value < this → feature drifted
PSI_WARNING = 0.10          # PSI 0.1–0.2 → slight drift
PSI_CRITICAL = 0.20         # PSI > 0.2 → major drift
ACCURACY_FLOOR = 0.50       # Rolling win rate below this → performance drift
MIN_TRADES_FOR_DRIFT = 10   # Need at least N closed trades to evaluate performance


# ---------------------------------------------------------------------------
# PSI (Population Stability Index)
# ---------------------------------------------------------------------------

def _psi(expected: np.ndarray, actual: np.ndarray, buckets: int = 10) -> float:
    """
    Compute PSI between two distributions.
    PSI < 0.10: no significant change
    PSI 0.10–0.20: slight change, monitor
    PSI > 0.20: significant change, retrain
    """
    eps = 1e-6
    bins = np.percentile(expected, np.linspace(0, 100, buckets + 1))
    bins[0] -= eps
    bins[-1] += eps

    expected_counts = np.histogram(expected, bins=bins)[0]
    actual_counts = np.histogram(actual, bins=bins)[0]

    expected_pct = expected_counts / (expected_counts.sum() + eps)
    actual_pct = actual_counts / (actual_counts.sum() + eps)

    expected_pct = np.clip(expected_pct, eps, None)
    actual_pct = np.clip(actual_pct, eps, None)

    psi = np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))
    return round(float(psi), 4)


# ---------------------------------------------------------------------------
# DriftDetector class
# ---------------------------------------------------------------------------

class DriftDetector:
    """
    Monitors data and model performance drift for a trading system.

    Parameters
    ----------
    reference_df  : DataFrame used as the baseline distribution (training window)
    ks_threshold  : KS test p-value threshold (default 0.05)
    acc_floor     : minimum acceptable rolling win rate (default 0.50)
    journal_path  : path to journal CSV for performance drift
    portfolio_path: path to paper portfolio JSON for consecutive-loss check
    """

    def __init__(
        self,
        reference_df: pd.DataFrame,
        ks_threshold: float = KS_P_THRESHOLD,
        acc_floor: float = ACCURACY_FLOOR,
        journal_path: Optional[str] = None,
        portfolio_path: Optional[str] = None,
    ):
        self.reference_df = reference_df
        self.ks_threshold = ks_threshold
        self.acc_floor = acc_floor
        self.journal_path = journal_path or "results/journal.csv"
        self.portfolio_path = portfolio_path or "results/paper_portfolio.json"

        # Feature columns to monitor (exclude non-numeric and target)
        exclude = {"target", "date", "ticker"}
        self._feature_cols = [
            c for c in reference_df.columns
            if c not in exclude and pd.api.types.is_numeric_dtype(reference_df[c])
        ]

    # ── Data Drift ────────────────────────────────────────────────────────

    def check_data_drift(self, live_df: pd.DataFrame) -> dict:
        """
        Run KS test + PSI on each feature column.

        Returns
        -------
        {
            "drifted_features": list[str],
            "feature_details": {feature: {"ks_stat", "ks_p", "psi", "drifted"}},
            "drift_ratio": float,   # fraction of features drifted
            "severity": "none" | "warning" | "critical",
        }
        """
        feature_details = {}
        drifted = []

        for col in self._feature_cols:
            if col not in live_df.columns:
                continue
            ref_vals = self.reference_df[col].dropna().values
            live_vals = live_df[col].dropna().values

            if len(ref_vals) < 5 or len(live_vals) < 5:
                continue

            ks_stat, ks_p = stats.ks_2samp(ref_vals, live_vals)
            psi = _psi(ref_vals, live_vals)
            is_drifted = ks_p < self.ks_threshold

            feature_details[col] = {
                "ks_stat": round(float(ks_stat), 4),
                "ks_p": round(float(ks_p), 4),
                "psi": psi,
                "drifted": is_drifted,
                "psi_status": (
                    "critical" if psi > PSI_CRITICAL
                    else "warning" if psi > PSI_WARNING
                    else "ok"
                ),
            }

            if is_drifted:
                drifted.append(col)

        n = len(feature_details)
        drift_ratio = len(drifted) / n if n > 0 else 0.0
        severity = (
            "critical" if drift_ratio > 0.3
            else "warning" if drift_ratio > 0.1
            else "none"
        )

        return {
            "drifted_features": drifted,
            "feature_details": feature_details,
            "drift_ratio": round(drift_ratio, 3),
            "severity": severity,
        }

    # ── Performance Drift ─────────────────────────────────────────────────

    def check_performance_drift(self) -> dict:
        """
        Check rolling 30-trade win rate from journal.csv.

        Returns
        -------
        {
            "total_closed": int,
            "rolling_30_win_rate": float | None,
            "acc_floor": float,
            "performance_drifted": bool,
            "consecutive_losses": int,
            "consecutive_loss_alert": bool,
        }
        """
        journal_path = Path(self.journal_path)
        if not journal_path.exists():
            logger.warning("Journal not found at %s", journal_path)
            return {
                "total_closed": 0,
                "rolling_30_win_rate": None,
                "acc_floor": self.acc_floor,
                "performance_drifted": False,
                "consecutive_losses": 0,
                "consecutive_loss_alert": False,
            }

        try:
            df = pd.read_csv(journal_path)
        except Exception as e:
            logger.error("Failed to read journal: %s", e)
            return {"performance_drifted": False, "consecutive_losses": 0, "consecutive_loss_alert": False}

        closed = df[df["outcome"].notna()].copy() if "outcome" in df.columns else pd.DataFrame()

        if closed.empty or len(closed) < MIN_TRADES_FOR_DRIFT:
            return {
                "total_closed": len(closed),
                "rolling_30_win_rate": None,
                "acc_floor": self.acc_floor,
                "performance_drifted": False,
                "consecutive_losses": 0,
                "consecutive_loss_alert": False,
            }

        closed["won"] = closed["outcome"].str.upper().isin(["WIN", "W", "1"])
        rolling_30 = closed["won"].iloc[-30:].mean()

        # Consecutive losses from the tail
        outcomes_tail = closed["won"].values[::-1]
        consecutive_losses = 0
        for o in outcomes_tail:
            if not o:
                consecutive_losses += 1
            else:
                break

        return {
            "total_closed": len(closed),
            "rolling_30_win_rate": round(float(rolling_30), 4),
            "acc_floor": self.acc_floor,
            "performance_drifted": rolling_30 < self.acc_floor,
            "consecutive_losses": consecutive_losses,
            "consecutive_loss_alert": consecutive_losses >= 5,
        }

    # ── Combined Report ───────────────────────────────────────────────────

    def run_full_check(self, live_df: pd.DataFrame, ticker: str = "") -> dict:
        """
        Run both data and performance drift checks and return a combined report.
        Sends a Telegram alert if any drift is detected.
        """
        data_report = self.check_data_drift(live_df)
        perf_report = self.check_performance_drift()

        any_drift = (
            data_report["severity"] != "none"
            or perf_report.get("performance_drifted")
            or perf_report.get("consecutive_loss_alert")
        )

        retrain_recommended = (
            data_report["severity"] == "critical"
            or perf_report.get("performance_drifted")
        )

        report = {
            "ticker": ticker,
            "data_drift": data_report,
            "performance_drift": perf_report,
            "any_drift": any_drift,
            "retrain_recommended": retrain_recommended,
        }

        if any_drift:
            self._send_alert(report)

        return report

    # ── Alert ─────────────────────────────────────────────────────────────

    def _send_alert(self, report: dict):
        """Send a Telegram alert via notify.py."""
        try:
            from src.notify import send

            ticker = report.get("ticker", "UNKNOWN")
            dd = report["data_drift"]
            pd_ = report["performance_drift"]

            lines = [f"⚠️ <b>DRIFT ALERT — {ticker}</b>"]

            # Data drift
            if dd["severity"] != "none":
                n_drifted = len(dd["drifted_features"])
                n_total = len(dd["feature_details"])
                lines.append(
                    f"📊 Data drift: {n_drifted}/{n_total} features drifted "
                    f"(severity: {dd['severity'].upper()})"
                )
                if dd["drifted_features"]:
                    top = ", ".join(dd["drifted_features"][:5])
                    lines.append(f"   Top drifted: {top}")

            # Performance drift
            wr = pd_.get("rolling_30_win_rate")
            if pd_.get("performance_drifted") and wr is not None:
                lines.append(
                    f"📉 Model accuracy: 30-trade win rate = {wr:.1%} "
                    f"(floor: {self.acc_floor:.1%})"
                )
            if pd_.get("consecutive_loss_alert"):
                losses = pd_.get("consecutive_losses", 0)
                lines.append(f"🔴 {losses} consecutive losses detected")

            # Recommendation
            if report.get("retrain_recommended"):
                lines.append("🔄 <b>Action: Retrain model recommended</b>")
            else:
                lines.append("👀 <b>Action: Monitor closely</b>")

            send("\n".join(lines))
        except Exception as e:
            logger.error("Failed to send drift alert: %s", e)


# ---------------------------------------------------------------------------
# Convenience: build DriftDetector from pipeline data
# ---------------------------------------------------------------------------

def build_detector(ticker: str, ref_years: int = 1, **kwargs) -> DriftDetector:
    """
    Build a DriftDetector using historical data as the reference distribution.

    Parameters
    ----------
    ticker    : e.g. "RELIANCE"
    ref_years : years of history to use as reference
    """
    from src.data_provider import load_bars
    from src.feature_engineering import add_features

    logger.info("Loading reference data for %s (%d years)…", ticker, ref_years)
    bars = load_bars(ticker, years=ref_years)
    features = add_features(bars, fetch_context=False)
    return DriftDetector(reference_df=features, **kwargs)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _print_report(report: dict):
    ticker = report.get("ticker", "UNKNOWN")
    dd = report["data_drift"]
    pd_ = report["performance_drift"]

    print(f"\n{'='*60}")
    print(f"  Drift Detection Report — {ticker}")
    print(f"{'='*60}")

    # Data drift summary
    print(f"\n  DATA DRIFT  (severity: {dd['severity'].upper()})")
    print(f"  Drift ratio: {dd['drift_ratio']:.1%} of features")
    if dd["drifted_features"]:
        print(f"  Drifted features:")
        for feat in dd["drifted_features"][:10]:
            det = dd["feature_details"][feat]
            print(
                f"    {feat:<25} KS-p={det['ks_p']:.4f}  PSI={det['psi']:.3f} [{det['psi_status']}]"
            )

    # Performance drift summary
    print(f"\n  PERFORMANCE DRIFT")
    wr = pd_.get("rolling_30_win_rate")
    if wr is not None:
        status = "⚠️  BELOW FLOOR" if pd_.get("performance_drifted") else "✅ OK"
        print(f"  Rolling 30-trade win rate: {wr:.1%}  {status}")
        print(f"  Floor: {pd_.get('acc_floor', 0.50):.1%}")
    else:
        print(f"  Not enough closed trades to evaluate (need {MIN_TRADES_FOR_DRIFT}+)")
    cl = pd_.get("consecutive_losses", 0)
    if cl >= 3:
        print(f"  ⚠️  Consecutive losses: {cl}")

    # Recommendation
    print(f"\n  RECOMMENDATION")
    if report.get("retrain_recommended"):
        print("  🔄 RETRAIN model — drift is significant")
    elif report.get("any_drift"):
        print("  👀 MONITOR closely — early drift signals")
    else:
        print("  ✅ No drift detected — model looks stable")

    print(f"{'='*60}\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Run drift detection")
    parser.add_argument("--ticker", default="RELIANCE", help="Stock ticker")
    parser.add_argument("--ref-days", type=int, default=252, help="Reference window (trading days)")
    parser.add_argument("--live-days", type=int, default=30, help="Live window to compare against")
    args = parser.parse_args()

    from src.data_provider import load_bars
    from src.feature_engineering import add_features

    print(f"Loading data for {args.ticker}…")
    bars = load_bars(args.ticker, years=max(1, (args.ref_days + args.live_days) // 252 + 1))
    all_features = add_features(bars, fetch_context=False)

    if len(all_features) < args.ref_days + args.live_days:
        print(f"Not enough data. Got {len(all_features)} rows, need {args.ref_days + args.live_days}.")
        raise SystemExit(1)

    reference_df = all_features.iloc[: -args.live_days]
    live_df = all_features.iloc[-args.live_days :]

    detector = DriftDetector(reference_df=reference_df)
    report = detector.run_full_check(live_df, ticker=args.ticker)
    _print_report(report)
