import pickle
from xgboost import XGBClassifier
from module2.algorithms.base import BaseAlgorithm


class XGBoostClassifierAlgorithm(BaseAlgorithm):
    """二分类/多分类，适用于 claim_flag 等离散标签。"""

    def train(self, X, y, params: dict):
        model = XGBClassifier(**params)
        model.fit(X, y)
        return model

    def save_model(self, model) -> bytes:
        return pickle.dumps(model)
