import pandas as pd
import ta
from bot.strategies.base import BaseStrategy

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


class MomentumStrategy(BaseStrategy):
    """
    BUY  : RSI entre 50-72 ET MACD positif ET prix > EMA20 ET hausse sur 3 bougies
    SELL : RSI < 45 OU MACD negatif ET prix < EMA20
    Suit les cryptos deja en forte hausse avec confirmation multiple.
    """
    name = "MOMENTUM"
    description = "Momentum fort — suit les cryptos deja en mouvement haussier"

    def __init__(self, ema_period=20, rsi_period=14, macd_fast=12,
                 macd_slow=26, macd_signal=9):
        self.ema_period = ema_period
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal

    def _compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"]
        df["ema"] = ta.trend.EMAIndicator(close, self.ema_period).ema_indicator()
        df["rsi"] = ta.momentum.RSIIndicator(close, self.rsi_period).rsi()
        macd = ta.trend.MACD(close, self.macd_fast, self.macd_slow, self.macd_signal)
        df["macd_diff"] = macd.macd_diff()
        df["returns"] = close.pct_change()
        return df

    def get_signal(self, df: pd.DataFrame) -> str:
        if len(df) < self.macd_slow + 10:
            return HOLD
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 4:
            return HOLD

        curr = df.iloc[-1]

        # Momentum haussier : 3 bougies consécutives en hausse
        last3_up = all(df["returns"].iloc[-i] > 0 for i in range(1, 4))
        above_ema = curr["close"] > curr["ema"]
        macd_positive = curr["macd_diff"] > 0
        rsi_momentum = 50 <= curr["rsi"] <= 72

        # Momentum perdu
        rsi_weak = curr["rsi"] < 45
        below_ema = curr["close"] < curr["ema"]
        macd_negative = curr["macd_diff"] < 0

        if last3_up and above_ema and macd_positive and rsi_momentum:
            return BUY
        if (rsi_weak or macd_negative) and below_ema:
            return SELL
        return HOLD

    def get_indicators(self, df: pd.DataFrame) -> dict:
        if len(df) < self.macd_slow + 10:
            return {}
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 1:
            return {}
        c = df.iloc[-1]
        return {
            "rsi": round(float(c["rsi"]), 1),
            "macd_diff": round(float(c["macd_diff"]), 5),
            "ema": round(float(c["ema"]), 4),
            "price": round(float(c["close"]), 4),
        }
