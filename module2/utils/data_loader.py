import pandas as pd
import io
import numpy as np

def load_data_from_bytes(data_bytes: bytes) -> (np.ndarray, np.ndarray):
    """解析 CSV，最后一列为标签"""
    df = pd.read_csv(io.BytesIO(data_bytes))
    X = df.iloc[:, :-1].values
    y = df.iloc[:, -1].values
    return X, y