from sklearn.ensemble import RandomForestRegressor

class TreeModel:
    def __init__(self, n_estimators=200, random_state=42):
        self.model = RandomForestRegressor(
            n_estimators=n_estimators,
            random_state=random_state
        )

    def fit(self, X, y):
        self.model.fit(X, y)

    def predict(self, X):
        return self.model.predict(X)
