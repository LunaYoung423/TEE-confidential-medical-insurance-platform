import pickle
from xgboost import XGBRegressor
from module2.algorithms.base import BaseAlgorithm

class XGBoostRegressionAlgorithm(BaseAlgorithm):
    def train(self, X, y, params: dict):
        # params 可传入 n_estimators, max_depth, learning_rate 等
        model = XGBRegressor(**params)
        model.fit(X, y)
        return model

    def save_model(self, model) -> bytes:
        return pickle.dumps(model)