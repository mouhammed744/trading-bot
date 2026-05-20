import pandas as pd
import ta
from bot.strategies.base import BaseStrategy

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


class EMACrossStrategy(BaseStrategy):
    """
    BUY  : EMA20 crosses above EMA50 AND RSI between 40-65 AND volume > average
    SELL : EMA20 crosses below EMA50 AND RSI between 35-60
    """
    name = "EMA_CROSS"
    description = "EMA 20/50 crossover with RSI and volume confirmation"

    def __init__(self, ema_fast=20, ema_slow=50, rsi_period=14, volume_ma=20):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_period = rsi_period
        self.volume_ma = volume_ma

    def _compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"]
        df["ema_fast"] = ta.trend.EMAIndicator(close, self.ema_fast).ema_indicator()
        df["ema_slow"] = ta.trend.EMAIndicator(close, self.ema_slow).ema_indicator()
        df["rsi"] = ta.momentum.RSIIndicator(close, self.rsi_period).rsi()
        df["vol_ma"] = df["volume"].rolling(self.volume_ma).mean()
        return df

    def get_signal(self, df: pd.DataFrame) -> str:
        if len(df) < self.ema_slow + 5:
            return HOLD
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 2:
            return HOLD

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        bullish_cross = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]
        bearish_cross = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]
        vol_ok = curr["volume"] > curr["vol_ma"]

        if bullish_cross and 40 <= curr["rsi"] <= 65 and vol_ok:
            return BUY
        if bearish_cross and 35 <= curr["rsi"] <= 60:
            return SELL
        return HOLD

    def get_indicators(self, df: pd.DataFrame) -> dict:
        if len(df) < self.ema_slow + 5:
            return {}
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 1:
            return {}
        c = df.iloc[-1]
        return {
            "ema_fast": round(float(c["ema_fast"]), 2),
            "ema_slow": round(float(c["ema_slow"]), 2),
            "rsi": round(float(c["rsi"]), 1),
            "vol": round(float(c["volume"]), 2),
            "vol_ma": round(float(c["vol_ma"]), 2),
        }
