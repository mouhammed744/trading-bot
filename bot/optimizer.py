"""
Auto-optimizer: after every N closed trades, tests different SL/TP values
on recent backtest data and saves the best parameters.
"""
import json
import logging
import os
from typing import Tuple

import pandas as pd

LEARNED_FILE = os.path.join("data", "learned_params.json")
OPTIMIZE_EVERY = 10   # run optimization after every 10 trades

logger = logging.getLogger("trading_bot.optimizer")


def _load_params() -> dict:
    if os.path.exists(LEARNED_FILE):
        try:
            with open(LEARNED_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Utilise les valeurs du .env comme défauts
    from bot import config
    return {"stop_loss_pct": config.STOP_LOSS_PCT, "take_profit_pct": config.TAKE_PROFIT_PCT,
            "optimized_at": None, "best_score": 0.0, "history": []}


def _save_params(params: dict):
    os.makedirs(os.path.dirname(LEARNED_FILE), exist_ok=True)
    with open(LEARNED_FILE, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2)


def load_best_params() -> Tuple[float, float]:
    p = _load_params()
    return p["stop_loss_pct"], p["take_profit_pct"]


def should_optimize(trade_count: int) -> bool:
    return trade_count > 0 and trade_count % OPTIMIZE_EVERY == 0


def optimize(df: pd.DataFrame, current_sl: float, current_tp: float) -> Tuple[float, float]:
    """
    Grid-search over SL/TP combinations on the provided DataFrame.
    Returns the (sl, tp) pair with the best compound PnL.
    """
    from bot.strategies.rsi_macd import RSIMACDStrategy

    strategy = RSIMACDStrategy()

    sl_values = [1.0, 1.5, 2.0, 2.5, 3.0]
    tp_values = [2.0, 3.0, 4.0, 5.0, 6.0]

    best_sl, best_tp = current_sl, current_tp
    best_score = -999.0
    results = []

    df_ind = df.copy()
    df_ind.dropna(inplace=True)

    for sl in sl_values:
        for tp in tp_values:
            if tp <= sl:
                continue
            score = _simulate(df_ind, strategy, sl, tp)
            results.append((sl, tp, score))
            if score > best_score:
                best_score = score
                best_sl, best_tp = sl, tp

    logger.info("Optimization complete: best SL=%.1f%% TP=%.1f%% score=%.2f%%",
                best_sl, best_tp, best_score)

    from datetime import datetime, timezone
    params = _load_params()
    params.update({
        "stop_loss_pct": best_sl,
        "take_profit_pct": best_tp,
        "best_score": round(best_score, 2),
        "optimized_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    })
    params.setdefault("history", []).append({
        "at": params["optimized_at"],
        "sl": best_sl, "tp": best_tp, "score": round(best_score, 2)
    })
    _save_params(params)
    return best_sl, best_tp


def _simulate(df: pd.DataFrame, strategy, sl_pct: float, tp_pct: float) -> float:
    """Quick simulation — returns compound PnL% across all trades."""
    capital = 10_000.0
    in_trade = False
    entry = 0.0

    for i in range(30, len(df)):
        close = float(df["close"].iloc[i])

        if in_trade:
            low  = float(df["low"].iloc[i])
            high = float(df["high"].iloc[i])
            sl = entry * (1 - sl_pct / 100)
            tp = entry * (1 + tp_pct / 100)
            if low <= sl:
                capital *= (1 - sl_pct / 100)
                in_trade = False
                continue
            if high >= tp:
                capital *= (1 + tp_pct / 100)
                in_trade = False
                continue

        if not in_trade:
            try:
                sig = strategy.get_signal(df.iloc[:i + 1])
            except Exception:
                sig = "HOLD"
            if sig == "BUY":
                entry = close
                in_trade = True

    return round((capital - 10_000) / 10_000 * 100, 2)
