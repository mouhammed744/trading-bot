from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    name: str = "base"
    description: str = ""

    @abstractmethod
    def get_signal(self, df: pd.DataFrame) -> str:
        """Return BUY / SELL / HOLD."""

    @abstractmethod
    def get_indicators(self, df: pd.DataFrame) -> dict:
        """Return current indicator values for logging."""
