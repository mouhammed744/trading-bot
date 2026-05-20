import pandas as pd
import ta
from bot.strategies.base import BaseStrategy

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


class RSIMACDStrategy(BaseStrategy):
    """
    BUY  : RSI was recently < 30 (last 5 candles) AND MACD bullish cross
           AND EMA9 approaching or above EMA21 AND volume > 20-period avg
    SELL : RSI > 70 AND MACD bearish cross AND EMA9 < EMA21
    """
    name = "RSI_MACD"
    description = "RSI oversold + MACD crossover + EMA trend + volume filter"

    def __init__(self, rsi_period=14, macd_fast=12, macd_slow=26, macd_signal=9,
                 ema_short=9, ema_long=21, volume_ma=20,
                 rsi_buy=30, rsi_sell=70):
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal_period = macd_signal
        self.ema_short = ema_short
        self.ema_long = ema_long
        self.volume_ma = volume_ma
        self.rsi_buy = rsi_buy
        self.rsi_sell = rsi_sell

    def _compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"]
        df["rsi"] = ta.momentum.RSIIndicator(close, window=self.rsi_period).rsi()
        macd = ta.trend.MACD(close, self.macd_fast, self.macd_slow, self.macd_signal_period)
        df["macd_diff"] = macd.macd_diff()
        df["ema_s"] = ta.trend.EMAIndicator(close, self.ema_short).ema_indicator()
        df["ema_l"] = ta.trend.EMAIndicator(close, self.ema_long).ema_indicator()
        df["vol_ma"] = df["volume"].rolling(self.volume_ma).mean()
        return df

    def get_signal(self, df: pd.DataFrame) -> str:
        if len(df) < 6:
            return HOLD
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 6:
            return HOLD

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        recent_rsi_min = float(df["rsi"].iloc[-6:-1].min())

        bullish_cross = prev["macd_diff"] < 0 and curr["macd_diff"] >= 0
        bearish_cross = prev["macd_diff"] > 0 and curr["macd_diff"] <= 0
        ema_ok = (curr["ema_s"] > curr["ema_l"]) or (
            (curr["ema_l"] - curr["ema_s"]) < (prev["ema_l"] - prev["ema_s"])
        )

        if (recent_rsi_min < self.rsi_buy and bullish_cross
                and ema_ok and curr["volume"] > curr["vol_ma"]):
            return BUY
        if (curr["rsi"] > self.rsi_sell and bearish_cross
                and curr["ema_s"] < curr["ema_l"]):
            return SELL
        return HOLD

    def get_indicators(self, df: pd.DataFrame) -> dict:
        if len(df) < 6:
            return {}
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 2:
            return {}
        c = df.iloc[-1]
        return {
            "rsi": round(float(c["rsi"]), 1),
            "rsi_min5": round(float(df["rsi"].iloc[-6:-1].min()), 1),
            "macd_diff": round(float(c["macd_diff"]), 4),
            "ema_s": round(float(c["ema_s"]), 2),
            "ema_l": round(float(c["ema_l"]), 2),
            "vol": round(float(c["volume"]), 2),
            "vol_ma": round(float(c["vol_ma"]), 2),
        }
