import pandas as pd
import ta
from bot.config import (
    RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    EMA_SHORT, EMA_LONG, VOLUME_MA_PERIOD,
)

SIGNAL_BUY = "BUY"
SIGNAL_SELL = "SELL"
SIGNAL_HOLD = "HOLD"


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add RSI, MACD, EMA, and volume MA columns to the DataFrame."""
    df = df.copy()
    close = df["close"]
    volume = df["volume"]

    # RSI
    df["rsi"] = ta.momentum.RSIIndicator(close, window=RSI_PERIOD).rsi()

    # MACD
    macd_obj = ta.trend.MACD(
        close, window_fast=MACD_FAST, window_slow=MACD_SLOW, window_sign=MACD_SIGNAL
    )
    df["macd"] = macd_obj.macd()
    df["macd_signal"] = macd_obj.macd_signal()
    df["macd_diff"] = macd_obj.macd_diff()  # histogram (macd - signal)

    # EMAs
    df["ema_short"] = ta.trend.EMAIndicator(close, window=EMA_SHORT).ema_indicator()
    df["ema_long"] = ta.trend.EMAIndicator(close, window=EMA_LONG).ema_indicator()

    # Volume moving average
    df["volume_ma"] = volume.rolling(window=VOLUME_MA_PERIOD).mean()

    return df


def _macd_bullish_cross(row_prev: pd.Series, row: pd.Series) -> bool:
    """MACD line crosses above signal line (histogram goes from negative to positive)."""
    return row_prev["macd_diff"] < 0 and row["macd_diff"] >= 0


def _macd_bearish_cross(row_prev: pd.Series, row: pd.Series) -> bool:
    """MACD line crosses below signal line (histogram goes from positive to negative)."""
    return row_prev["macd_diff"] > 0 and row["macd_diff"] <= 0


def get_signal(df: pd.DataFrame) -> str:
    """
    Evaluate the last candles and return BUY / SELL / HOLD.

    BUY  : MACD bullish cross  AND RSI was recently oversold (min RSI over last 5 candles < 30)
           AND EMA short > EMA long (uptrend) OR EMA gap narrowing (recovering)
           AND volume > volume_ma
    SELL : RSI > 70  AND MACD bearish cross  AND ema_short < ema_long

    Using "recently oversold" instead of "currently < 30" because in practice the MACD
    bullish cross happens 1-3 candles AFTER the RSI bottom — they never coincide exactly.
    """
    if len(df) < 6:
        return SIGNAL_HOLD

    df = compute_indicators(df)
    df.dropna(inplace=True)

    if len(df) < 6:
        return SIGNAL_HOLD

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    rsi = curr["rsi"]
    ema_short = curr["ema_short"]
    ema_long = curr["ema_long"]
    volume = curr["volume"]
    volume_ma = curr["volume_ma"]

    # RSI was oversold within the last 5 closed candles
    recent_rsi_min = df["rsi"].iloc[-6:-1].min()

    # EMA: uptrend OR gap narrowing (short recovering toward long)
    prev_gap = float(prev["ema_long"] - prev["ema_short"])
    curr_gap = float(ema_long - ema_short)
    ema_ok = (ema_short > ema_long) or (curr_gap < prev_gap)

    if (
        recent_rsi_min < 30
        and _macd_bullish_cross(prev, curr)
        and ema_ok
        and volume > volume_ma
    ):
        return SIGNAL_BUY

    if (
        rsi > 70
        and _macd_bearish_cross(prev, curr)
        and ema_short < ema_long
    ):
        return SIGNAL_SELL

    return SIGNAL_HOLD


def get_signal_with_indicators(df: pd.DataFrame) -> dict:
    """Return signal plus the current indicator values for logging/debugging."""
    if len(df) < 6:
        return {"signal": SIGNAL_HOLD}

    df = compute_indicators(df)
    df.dropna(inplace=True)

    if len(df) < 6:
        return {"signal": SIGNAL_HOLD}

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    recent_rsi_min = float(df["rsi"].iloc[-6:-1].min())

    signal = get_signal(df)

    return {
        "signal": signal,
        "rsi": round(float(curr["rsi"]), 2),
        "rsi_min_5": round(recent_rsi_min, 2),
        "macd": round(float(curr["macd"]), 6),
        "macd_signal": round(float(curr["macd_signal"]), 6),
        "macd_diff": round(float(curr["macd_diff"]), 6),
        "ema_short": round(float(curr["ema_short"]), 2),
        "ema_long": round(float(curr["ema_long"]), 2),
        "volume": round(float(curr["volume"]), 4),
        "volume_ma": round(float(curr["volume_ma"]), 4),
        "prev_macd_diff": round(float(prev["macd_diff"]), 6),
    }
