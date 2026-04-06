"""
Compare MLflow experiment runs and identify the best model configuration.

Usage:
    python scripts/compare_models.py
    python scripts/compare_models.py --ticker RELIANCE
    python scripts/compare_models.py --metric win_rate --top 10
"""

import argparse
import sys
import os

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main():
    parser = argparse.ArgumentParser(description="Compare MLflow model runs")
    parser.add_argument("--ticker", default=None, help="Filter by ticker (e.g. RELIANCE)")
    parser.add_argument(
        "--metric",
        default="sharpe_ratio",
        choices=["sharpe_ratio", "win_rate", "profit_factor", "accuracy", "max_drawdown"],
        help="Primary ranking metric (default: sharpe_ratio)",
    )
    parser.add_argument("--top", type=int, default=10, help="Number of runs to display")
    args = parser.parse_args()

    try:
        import mlflow
    except ImportError:
        print("ERROR: mlflow not installed. Run: pip install mlflow")
        sys.exit(1)

    from src.mlflow_tracker import TRACKING_URI, EXPERIMENT_NAME

    mlflow.set_tracking_uri(TRACKING_URI)
    client = mlflow.tracking.MlflowClient(tracking_uri=TRACKING_URI)

    exp = client.get_experiment_by_name(EXPERIMENT_NAME)
    if exp is None:
        print(f"No experiment '{EXPERIMENT_NAME}' found. Run the pipeline first:")
        print("  python -m src.pipeline --ticker RELIANCE --years 3")
        sys.exit(0)

    filter_str = ""
    if args.ticker:
        filter_str = f"tags.ticker = '{args.ticker}'"

    # Ascending for drawdown (lower is better), descending otherwise
    ascending = args.metric == "max_drawdown"
    order = f"metrics.{args.metric} {'ASC' if ascending else 'DESC'}"

    runs = client.search_runs(
        experiment_ids=[exp.experiment_id],
        filter_string=filter_str,
        order_by=[order],
        max_results=args.top,
    )

    if not runs:
        print("No runs found. Train a model first:")
        print("  python -m src.pipeline --ticker RELIANCE --years 3")
        return

    # ── Print comparison table ──────────────────────────────────────────────
    header_cols = ["rank", "run_id", "ticker", "model_type", "sharpe", "win_rate", "pf", "trades", "drawdown"]
    col_widths  = [4,       12,       10,        12,           8,        9,          6,    7,         9]

    def _fmt(val, width):
        if val is None:
            return "-".ljust(width)
        if isinstance(val, float):
            return f"{val:.3f}".ljust(width)
        return str(val)[:width].ljust(width)

    separator = "─" * sum(col_widths + [len(header_cols) * 2])
    header = "  ".join(c.ljust(w) for c, w in zip(header_cols, col_widths))

    print(f"\n{'='*len(separator)}")
    print(f"  MLflow Run Comparison — Experiment: {EXPERIMENT_NAME}")
    if args.ticker:
        print(f"  Ticker filter: {args.ticker}")
    print(f"  Ranked by: {args.metric} ({'lower is better' if ascending else 'higher is better'})")
    print(f"{'='*len(separator)}")
    print(header)
    print(separator)

    best_run = None
    for rank, run in enumerate(runs, 1):
        m = run.data.metrics
        p = run.data.params
        t = run.data.tags

        row = [
            str(rank),
            run.info.run_id[:10],
            t.get("ticker", "-"),
            t.get("model_type", "-"),
            m.get("sharpe_ratio"),
            m.get("win_rate"),
            m.get("profit_factor"),
            m.get("total_trades"),
            m.get("max_drawdown"),
        ]
        print("  ".join(_fmt(v, w) for v, w in zip(row, col_widths)))

        if rank == 1:
            best_run = run

    print(separator)

    # ── Recommended config ──────────────────────────────────────────────────
    if best_run:
        print(f"\n{'='*len(separator)}")
        print("  RECOMMENDED CONFIGURATION (Best Run)")
        print(f"{'='*len(separator)}")
        print(f"  Run ID    : {best_run.info.run_id}")
        print(f"  Ticker    : {best_run.data.tags.get('ticker', '-')}")
        print(f"  Model type: {best_run.data.tags.get('model_type', '-')}")
        print()
        print("  Parameters:")
        for k, v in sorted(best_run.data.params.items()):
            if k not in ("ticker", "model_type", "dataset_rows", "dataset_hash"):
                print(f"    {k}: {v}")
        print()
        print("  Metrics:")
        for k, v in sorted(best_run.data.metrics.items()):
            print(f"    {k}: {v:.4f}")
        print()
        print("  To reproduce:")
        ticker = best_run.data.tags.get("ticker", "RELIANCE")
        years = best_run.data.params.get("years", 5)
        threshold = best_run.data.params.get("confidence_threshold", 0.62)
        print(f"    python -m src.pipeline --ticker {ticker} --years {years} --threshold {threshold}")
        print()
        print("  To explore all runs visually:")
        print("    mlflow ui")
        print(f"{'='*len(separator)}\n")


if __name__ == "__main__":
    main()
