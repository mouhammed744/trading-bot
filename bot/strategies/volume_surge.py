import pandas as pd
import ta
from bot.strategies.base import BaseStrategy

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


class VolumeSurgeStrategy(BaseStrategy):
    """
    BUY  : Volume spike > 3x moyenne ET prix en hausse ET RSI < 70
    SELL : Volume retombe < 0.8x moyenne ET RSI > 65
    Detecte les gros mouvements de capitaux (baleines, news, listings).
    """
    name = "VOLUME_SURGE"
    description = "Volume spike 3x+ avec confirmation de prix haussier"

    def __init__(self, volume_ma=20, surge_mult=3.0, rsi_period=14,
                 rsi_buy=70, rsi_sell=65, vol_exit_mult=0.8):
        self.volume_ma = volume_ma
        self.surge_mult = surge_mult
        self.rsi_period = rsi_period
        self.rsi_buy = rsi_buy
        self.rsi_sell = rsi_sell
        self.vol_exit_mult = vol_exit_mult

    def _compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["vol_ma"] = df["volume"].rolling(self.volume_ma).mean()
        df["vol_ratio"] = df["volume"] / df["vol_ma"]
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], self.rsi_period).rsi()
        df["price_change"] = df["close"].pct_change()
        return df

    def get_signal(self, df: pd.DataFrame) -> str:
        if len(df) < self.volume_ma + 5:
            return HOLD
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 2:
            return HOLD

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        surge = curr["vol_ratio"] >= self.surge_mult
        price_up = curr["price_change"] > 0 and prev["price_change"] > 0
        vol_cooling = curr["vol_ratio"] < self.vol_exit_mult

        if surge and price_up and curr["rsi"] < self.rsi_buy:
            return BUY
        if vol_cooling and curr["rsi"] > self.rsi_sell:
            return SELL
        return HOLD

    def get_indicators(self, df: pd.DataFrame) -> dict:
        if len(df) < self.volume_ma + 5:
            return {}
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 1:
            return {}
        c = df.iloc[-1]
        return {
            "vol_ratio": round(float(c["vol_ratio"]), 2),
            "rsi": round(float(c["rsi"]), 1),
            "price_change_pct": round(float(c["price_change"]) * 100, 3),
        }
