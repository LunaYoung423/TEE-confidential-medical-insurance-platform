from abc import ABC, abstractmethod

class BaseAlgorithm(ABC):
    @abstractmethod
    def train(self, X, y, params: dict):
        """训练模型，返回模型对象"""
        pass

    @abstractmethod
    def save_model(self, model) -> bytes:
        """将模型序列化为 bytes"""
        pass