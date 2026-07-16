"""
UPGRADE 5: MLflow Experiment Tracking

Wraps model training runs with MLflow logging.
Storage: local ./mlruns directory (zero-config, view with `mlflow ui`).

Usage in pipeline.py:
    import src.mlflow_tracker as tracker
    with tracker.start_run(ticker="RELIANCE", model_type="ensemble", params={...}):
        # train models ...
        tracker.log_metrics({"sharpe": 1.4, "win_rate": 0.58})
        tracker.log_model_artifact(tree_model.model, "tree_model")
"""

import hashlib
import io
import logging
import os
import pickle
import tempfile
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# MLflow tracking URI — local by default, override with MLFLOW_TRACKING_URI env var
TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "mlruns")
EXPERIMENT_NAME = os.environ.get("MLFLOW_EXPERIMENT", "stock-forecasting")

# mlflow >=3 puts the plain file store in maintenance mode and raises unless this
# is set — we want the zero-config local file store (see module docstring), not a DB.
os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")


def _get_client():
    try:
        import mlflow
        mlflow.set_tracking_uri(TRACKING_URI)
        return mlflow
    except ImportError:
        logger.error("mlflow not installed. Run: pip install mlflow")
        return None


def _ensure_experiment(mlflow) -> str:
    """Create experiment if it doesn't exist; return experiment_id."""
    exp = mlflow.get_experiment_by_name(EXPERIMENT_NAME)
    if exp is None:
        return mlflow.create_experiment(EXPERIMENT_NAME)
    return exp.experiment_id


# ---------------------------------------------------------------------------
# Context manager: start_run
# ---------------------------------------------------------------------------

class start_run:
    """
    Context manager that wraps a training run with MLflow tracking.

    Usage:
        with tracker.start_run("RELIANCE", "ensemble", {"threshold": 0.62}) as run:
            tracker.log_metrics({"sharpe": 1.4})
        print(run.info.run_id)
    """

    def __init__(
        self,
        ticker: str,
        model_type: str,
        params: dict,
        tags: Optional[dict] = None,
    ):
        self.ticker = ticker
        self.model_type = model_type
        self.params = params
        self.tags = tags or {}
        self._mlflow = None
        self._run = None

    def __enter__(self):
        mlflow = _get_client()
        if mlflow is None:
            return self
        self._mlflow = mlflow
        exp_id = _ensure_experiment(mlflow)
        self._run = mlflow.start_run(
            experiment_id=exp_id,
            tags={"ticker": self.ticker, "model_type": self.model_type, **self.tags},
        )
        mlflow.log_params({"ticker": self.ticker, "model_type": self.model_type})
        mlflow.log_params(self.params)
        return self._run

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._mlflow and self._run:
            self._mlflow.end_run(status="FAILED" if exc_type else "FINISHED")
        return False  # don't suppress exceptions


# ---------------------------------------------------------------------------
# Logging helpers (call inside start_run context)
# ---------------------------------------------------------------------------

def log_metrics(metrics: dict):
    """
    Log scalar metrics to the active MLflow run.

    Recommended metrics:
        sharpe_ratio, win_rate, profit_factor, max_drawdown,
        total_trades, mae, rmse, accuracy
    """
    mlflow = _get_client()
    if mlflow is None:
        return
    try:
        mlflow.log_metrics({k: float(v) for k, v in metrics.items() if v is not None})
    except Exception as e:
        logger.warning("MLflow log_metrics failed: %s", e)


def log_dataset_hash(df: pd.DataFrame):
    """Log a reproducibility hash of the dataset (shape + date range)."""
    mlflow = _get_client()
    if mlflow is None:
        return
    try:
        summary = f"{df.shape}_{df.index[0]}_{df.index[-1]}"
        h = hashlib.md5(summary.encode()).hexdigest()[:12]
        mlflow.log_params({"dataset_hash": h, "dataset_rows": len(df)})
    except Exception as e:
        logger.warning("MLflow log_dataset_hash failed: %s", e)


def log_feature_importance(model: Any, feature_names: list):
    """
    Log feature importance bar chart as a PNG artifact.
    Works with tree models that have a feature_importances_ attribute.
    """
    mlflow = _get_client()
    if mlflow is None:
        return
    try:
        import matplotlib.pyplot as plt
        import numpy as np

        # Try .feature_importances_ (sklearn/lgbm/xgb) or .feature_importance() method
        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
        elif hasattr(model, "feature_importance"):
            importances = model.feature_importance()
            if hasattr(importances, "values"):
                importances = importances.values
        else:
            logger.warning("Model has no feature importance attribute; skipping.")
            return

        idx = np.argsort(importances)[::-1][:20]
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.barh(
            [feature_names[i] for i in idx[::-1]],
            importances[idx[::-1]],
        )
        ax.set_title("Top 20 Feature Importances")
        ax.set_xlabel("Importance")
        plt.tight_layout()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            fig.savefig(f.name, dpi=100)
            mlflow.log_artifact(f.name, artifact_path="plots")
        plt.close(fig)
    except Exception as e:
        logger.warning("MLflow log_feature_importance failed: %s", e)


def log_model_artifact(model: Any, name: str):
    """Pickle the model and log it as an MLflow artifact."""
    mlflow = _get_client()
    if mlflow is None:
        return
    try:
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            pickle.dump(model, f)
            mlflow.log_artifact(f.name, artifact_path=f"models/{name}")
    except Exception as e:
        logger.warning("MLflow log_model_artifact failed: %s", e)


# ---------------------------------------------------------------------------
# Query: best run
# ---------------------------------------------------------------------------

def get_best_run(
    metric: str = "sharpe_ratio",
    ticker: Optional[str] = None,
) -> dict:
    """
    Return the best MLflow run for a given metric (higher = better).

    Parameters
    ----------
    metric : metric name to rank by (must have been logged via log_metrics)
    ticker : optional filter by ticker tag

    Returns
    -------
    dict with keys: run_id, ticker, model_type, metrics, params
    """
    mlflow = _get_client()
    if mlflow is None:
        return {}
    try:
        client = mlflow.tracking.MlflowClient(tracking_uri=TRACKING_URI)
        exp = client.get_experiment_by_name(EXPERIMENT_NAME)
        if exp is None:
            logger.warning("No experiment named '%s' found.", EXPERIMENT_NAME)
            return {}

        filter_str = f"metrics.{metric} > 0"
        if ticker:
            filter_str += f" and tags.ticker = '{ticker}'"

        runs = client.search_runs(
            experiment_ids=[exp.experiment_id],
            filter_string=filter_str,
            order_by=[f"metrics.{metric} DESC"],
            max_results=1,
        )

        if not runs:
            return {}

        best = runs[0]
        return {
            "run_id": best.info.run_id,
            "ticker": best.data.tags.get("ticker"),
            "model_type": best.data.tags.get("model_type"),
            "metrics": dict(best.data.metrics),
            "params": dict(best.data.params),
        }
    except Exception as e:
        logger.error("MLflow get_best_run failed: %s", e)
        return {}


if __name__ == "__main__":
    import json
    best = get_best_run("sharpe_ratio")
    print("Best run:", json.dumps(best, indent=2))
