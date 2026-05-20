import pandas as pd
import ta
from bot.strategies.base import BaseStrategy

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


class BreakoutStrategy(BaseStrategy):
    """
    Momentum breakout strategy.
    BUY  : price breaks above N-period high AND volume > 1.5x avg AND ADX > 25 (strong trend)
    SELL : price breaks below N-period low  AND ADX > 25
    """
    name = "BREAKOUT"
    description = "Price breakout above/below N-period high/low with volume and ADX confirmation"

    def __init__(self, lookback=20, volume_ma=20, adx_period=14, adx_threshold=25):
        self.lookback = lookback
        self.volume_ma_period = volume_ma
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold

    def _compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["resistance"] = df["high"].shift(1).rolling(self.lookback).max()
        df["support"]    = df["low"].shift(1).rolling(self.lookback).min()
        df["vol_ma"]     = df["volume"].rolling(self.volume_ma_period).mean()
        adx = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], self.adx_period)
        df["adx"] = adx.adx()
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], 14).rsi()
        return df

    def get_signal(self, df: pd.DataFrame) -> str:
        if len(df) < self.lookback + 5:
            return HOLD
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 2:
            return HOLD

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        strong_trend = curr["adx"] > self.adx_threshold
        vol_spike    = curr["volume"] > curr["vol_ma"] * 1.5

        # Breakout: price crosses above resistance
        bullish_break = prev["close"] <= prev["resistance"] and curr["close"] > curr["resistance"]
        # Breakdown: price crosses below support
        bearish_break = prev["close"] >= prev["support"] and curr["close"] < curr["support"]

        if bullish_break and strong_trend and vol_spike and curr["rsi"] < 75:
            return BUY
        if bearish_break and strong_trend and vol_spike and curr["rsi"] > 25:
            return SELL
        return HOLD

    def get_indicators(self, df: pd.DataFrame) -> dict:
        if len(df) < self.lookback + 5:
            return {}
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 1:
            return {}
        c = df.iloc[-1]
        return {
            "adx": round(float(c["adx"]), 1),
            "rsi": round(float(c["rsi"]), 1),
            "resistance": round(float(c["resistance"]), 2),
            "support": round(float(c["support"]), 2),
            "price": round(float(c["close"]), 2),
            "vol": round(float(c["volume"]), 2),
            "vol_ma": round(float(c["vol_ma"]), 2),
        }
