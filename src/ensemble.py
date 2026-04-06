import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV


class EnsembleModel:
    """
    Meta-learner (stacking ensemble).

    Base models feed probability estimates into a Logistic Regression
    meta-learner that learns which base model to trust in different
    market conditions.

    Signal confidence filter:
      - Only trades where meta-model confidence >= threshold are surfaced.
      - Adjusts position size proportional to confidence above threshold.
    """

    def __init__(self, confidence_threshold: float = 0.62):
        self.threshold = confidence_threshold
        self.meta = CalibratedClassifierCV(
            LogisticRegression(C=0.1, max_iter=1000, random_state=42),
            method="isotonic",
            cv=5,
        )
        self._is_fitted = False

    # ── Training ──────────────────────────────────────────────────────────────

    def fit(self, base_probas: dict[str, np.ndarray], y: np.ndarray):
        """
        Parameters
        ----------
        base_probas : dict mapping model name → 1-D array of P(UP) estimates
        y           : ground truth (0/1 array)
        """
        X_meta = self._stack(base_probas)
        self.meta.fit(X_meta, y)
        self._is_fitted = True

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict_proba(self, base_probas: dict[str, np.ndarray]) -> np.ndarray:
        X_meta = self._stack(base_probas)
        return self.meta.predict_proba(X_meta)[:, 1]

    def predict(self, base_probas: dict[str, np.ndarray]) -> np.ndarray:
        return (self.predict_proba(base_probas) >= 0.5).astype(int)

    def signals(self, base_probas: dict[str, np.ndarray]) -> pd.DataFrame:
        """
        Returns a DataFrame with:
          - confidence : meta-model P(UP)
          - signal     : 1 (BUY) / -1 (SELL) / 0 (NO TRADE)
          - size_factor: fractional position size based on confidence margin
        """
        conf = self.predict_proba(base_probas)
        n = len(conf)

        signal = np.zeros(n, dtype=int)
        signal[conf >= self.threshold] = 1         # BUY
        signal[conf <= (1 - self.threshold)] = -1  # SELL

        # Scale size linearly with confidence above threshold
        margin = np.abs(conf - 0.5)
        size_factor = np.clip((margin - (self.threshold - 0.5)) / 0.5, 0, 1)

        return pd.DataFrame({
            "confidence": np.round(conf, 4),
            "signal": signal,
            "size_factor": np.round(size_factor, 4),
        })

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _stack(base_probas: dict[str, np.ndarray]) -> np.ndarray:
        arrays = list(base_probas.values())
        return np.column_stack(arrays)
