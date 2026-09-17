from .logistic_regression import LogisticRegressionAlgorithm
from .xgboost_model import XGBoostRegressionAlgorithm
from .xgboost_classifier import XGBoostClassifierAlgorithm

def get_algorithm(alg_type: str):
    if alg_type == "logistic_regression":
        return LogisticRegressionAlgorithm()
    elif alg_type == "xgboost":
        return XGBoostRegressionAlgorithm()
    elif alg_type == "xgboost_classifier":
        return XGBoostClassifierAlgorithm()
    else:
        raise ValueError(f"Unsupported algorithm: {alg_type}")