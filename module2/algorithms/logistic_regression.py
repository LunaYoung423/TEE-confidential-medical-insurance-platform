import pickle
from sklearn.linear_model import LogisticRegression
from module2.algorithms.base import BaseAlgorithm

class LogisticRegressionAlgorithm(BaseAlgorithm):
    def train(self, X, y, params: dict):
        model = LogisticRegression(**params)
        model.fit(X, y)
        return model

    def save_model(self, model) -> bytes:
        return pickle.dumps(model)