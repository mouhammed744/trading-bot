import pandas as pd
import ta
from bot.strategies.base import BaseStrategy

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


class StochRSIStrategy(BaseStrategy):
    """
    BUY  : Stoch RSI K crosses above 20 (sortie zone survendu)
           AND price > EMA50 (tendance haussiere) AND volume spike
    SELL : Stoch RSI K crosses below 80 (sortie zone surachete)
           AND price < EMA50
    """
    name = "STOCH_RSI"
    description = "Stochastic RSI oversold/overbought exit with EMA trend filter"

    def __init__(self, rsi_period=14, stoch_period=14, smooth_k=3, smooth_d=3,
                 ema_period=50, volume_ma=20):
        self.rsi_period = rsi_period
        self.stoch_period = stoch_period
        self.smooth_k = smooth_k
        self.smooth_d = smooth_d
        self.ema_period = ema_period
        self.volume_ma = volume_ma

    def _compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"]
        stoch = ta.momentum.StochRSIIndicator(
            close, self.rsi_period, self.stoch_period, self.smooth_k, self.smooth_d
        )
        df["stoch_k"] = stoch.stochrsi_k() * 100
        df["stoch_d"] = stoch.stochrsi_d() * 100
        df["ema50"] = ta.trend.EMAIndicator(close, self.ema_period).ema_indicator()
        df["rsi"] = ta.momentum.RSIIndicator(close, self.rsi_period).rsi()
        df["vol_ma"] = df["volume"].rolling(self.volume_ma).mean()
        return df

    def get_signal(self, df: pd.DataFrame) -> str:
        if len(df) < self.ema_period + self.stoch_period + 10:
            return HOLD
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 2:
            return HOLD

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # K crosses above 20 (sortie survendu)
        cross_up = prev["stoch_k"] <= 20 and curr["stoch_k"] > 20
        # K crosses below 80 (sortie surachete)
        cross_down = prev["stoch_k"] >= 80 and curr["stoch_k"] < 80

        trend_up = curr["close"] > curr["ema50"]
        trend_down = curr["close"] < curr["ema50"]
        vol_spike = curr["volume"] > curr["vol_ma"] * 1.1

        if cross_up and trend_up and vol_spike and curr["rsi"] < 65:
            return BUY
        if cross_down and trend_down and curr["rsi"] > 35:
            return SELL
        return HOLD

    def get_indicators(self, df: pd.DataFrame) -> dict:
        if len(df) < self.ema_period + self.stoch_period + 10:
            return {}
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 1:
            return {}
        c = df.iloc[-1]
        return {
            "stoch_k": round(float(c["stoch_k"]), 1),
            "stoch_d": round(float(c["stoch_d"]), 1),
            "rsi": round(float(c["rsi"]), 1),
            "ema50": round(float(c["ema50"]), 2),
            "vol": round(float(c["volume"]), 2),
            "vol_ma": round(float(c["vol_ma"]), 2),
        }
