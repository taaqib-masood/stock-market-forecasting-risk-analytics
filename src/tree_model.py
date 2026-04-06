import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

try:
    import lightgbm as lgb
    _LGB = True
except ImportError:
    _LGB = False


class TreeModel:
    """
    Directional classifier.
    Uses LightGBM if available (faster, better on tabular financial data),
    falls back to RandomForest.
    Target: 1 = next-day close UP, 0 = DOWN.
    """

    def __init__(self, n_estimators: int = 500, random_state: int = 42):
        if _LGB:
            self.model = lgb.LGBMClassifier(
                n_estimators=n_estimators,
                learning_rate=0.05,
                max_depth=6,
                num_leaves=31,
                min_child_samples=20,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=random_state,
                verbose=-1,
            )
        else:
            self.model = RandomForestClassifier(
                n_estimators=n_estimators,
                max_depth=8,
                min_samples_leaf=10,
                random_state=random_state,
                n_jobs=-1,
            )
        self.feature_names = None

    def fit(self, X: pd.DataFrame, y: pd.Series):
        self.feature_names = list(X.columns)
        self.model.fit(X, y)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Returns probability of class 1 (UP)."""
        return self.model.predict_proba(X)[:, 1]

    def feature_importance(self) -> pd.Series:
        if self.feature_names is None:
            return pd.Series(dtype=float)
        imp = getattr(self.model, "feature_importances_", None)
        if imp is None:
            return pd.Series(dtype=float)
        return pd.Series(imp, index=self.feature_names).sort_values(ascending=False)
