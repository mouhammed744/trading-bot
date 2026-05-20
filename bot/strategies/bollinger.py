import pandas as pd
import ta
from bot.strategies.base import BaseStrategy

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


class BollingerStrategy(BaseStrategy):
    """
    Mean-reversion on Bollinger Bands.
    BUY  : price touches lower band AND RSI < 40 AND volume spike
    SELL : price touches upper band AND RSI > 60
    """
    name = "BOLLINGER"
    description = "Bollinger Bands mean-reversion with RSI + volume confirmation"

    def __init__(self, bb_period=20, bb_std=2.0, rsi_period=14,
                 rsi_buy=40, rsi_sell=60, volume_ma=20):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_buy = rsi_buy
        self.rsi_sell = rsi_sell
        self.volume_ma_period = volume_ma

    def _compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"]
        bb = ta.volatility.BollingerBands(close, self.bb_period, self.bb_std)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_mid"]   = bb.bollinger_mavg()
        df["bb_pct"]   = bb.bollinger_pband()   # 0=lower band, 1=upper band
        df["rsi"]      = ta.momentum.RSIIndicator(close, self.rsi_period).rsi()
        df["vol_ma"]   = df["volume"].rolling(self.volume_ma_period).mean()
        return df

    def get_signal(self, df: pd.DataFrame) -> str:
        if len(df) < self.bb_period + 5:
            return HOLD
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 2:
            return HOLD

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # Price was at or below lower band in last 2 candles (touch)
        touched_lower = prev["close"] <= prev["bb_lower"] or curr["close"] <= curr["bb_lower"]
        # Price bouncing back above lower band
        bouncing = curr["close"] > curr["bb_lower"] and prev["close"] <= prev["bb_lower"]
        vol_spike = curr["volume"] > curr["vol_ma"] * 1.2

        touched_upper = prev["close"] >= prev["bb_upper"] or curr["close"] >= curr["bb_upper"]
        declining = curr["close"] < curr["bb_upper"] and prev["close"] >= prev["bb_upper"]

        if touched_lower and bouncing and curr["rsi"] < self.rsi_buy and vol_spike:
            return BUY
        if touched_upper and declining and curr["rsi"] > self.rsi_sell:
            return SELL
        return HOLD

    def get_indicators(self, df: pd.DataFrame) -> dict:
        if len(df) < self.bb_period + 5:
            return {}
        df = self._compute(df)
        df.dropna(inplace=True)
        if len(df) < 1:
            return {}
        c = df.iloc[-1]
        return {
            "rsi": round(float(c["rsi"]), 1),
            "bb_pct": round(float(c["bb_pct"]), 3),
            "bb_lower": round(float(c["bb_lower"]), 2),
            "bb_upper": round(float(c["bb_upper"]), 2),
            "price": round(float(c["close"]), 2),
            "vol": round(float(c["volume"]), 2),
            "vol_ma": round(float(c["vol_ma"]), 2),
        }
