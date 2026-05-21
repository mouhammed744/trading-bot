"""
Manages multiple strategies, scores them based on past performance,
and selects the best signal using weighted voting.
"""
import json
import logging
import os
import tempfile
from typing import List, Optional
import pandas as pd

from bot.strategies.base import BaseStrategy
from bot.strategies.rsi_macd import RSIMACDStrategy
from bot.strategies.bollinger import BollingerStrategy
from bot.strategies.breakout import BreakoutStrategy
from bot.strategies.ema_cross import EMACrossStrategy
from bot.strategies.stoch_rsi import StochRSIStrategy
from bot.strategies.volume_surge import VolumeSurgeStrategy
from bot.strategies.momentum import MomentumStrategy

SCORES_FILE = os.path.join("data", "strategy_scores.json")
BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"

logger = logging.getLogger("trading_bot.strategy_manager")


def _default_scores(strategies):
    return {s.name: {"weight": 1.0, "trades": 0, "wins": 0,
                     "total_pnl": 0.0, "win_rate": 0.0} for s in strategies}


class StrategyManager:
    def __init__(self, strategies: Optional[List[BaseStrategy]] = None):
        self.strategies: List[BaseStrategy] = strategies or [
            RSIMACDStrategy(),
            BollingerStrategy(),
            BreakoutStrategy(),
            EMACrossStrategy(),
            StochRSIStrategy(),
            VolumeSurgeStrategy(),
            MomentumStrategy(),
        ]
        self._scores = self._load_scores()

    # ------------------------------------------------------------------
    # Signal aggregation
    # ------------------------------------------------------------------

    def get_signal(self, df: pd.DataFrame) -> dict:
        """
        Ask all strategies for a signal. Use weighted voting:
        - BUY wins if weighted BUY votes > weighted SELL votes and > threshold
        - Returns the winning signal and which strategies voted for it.
        """
        votes = {BUY: 0.0, SELL: 0.0, HOLD: 0.0}
        details = {}

        for s in self.strategies:
            try:
                signal = s.get_signal(df)
                indicators = s.get_indicators(df)
                weight = self._scores.get(s.name, {}).get("weight", 1.0)
                votes[signal] += weight
                details[s.name] = {"signal": signal, "weight": round(weight, 2), **indicators}
                logger.debug("%s -> %s (weight=%.2f)", s.name, signal, weight)
            except Exception as exc:
                logger.warning("Strategy %s error: %s", s.name, exc)
                details[s.name] = {"signal": HOLD, "weight": 1.0, "error": str(exc)}

        # Determine winner
        total_weight = sum(self._scores.get(s.name, {}).get("weight", 1.0)
                           for s in self.strategies)
        buy_pct  = votes[BUY]  / total_weight
        sell_pct = votes[SELL] / total_weight

        from bot import config
        threshold = getattr(config, "SIGNAL_THRESHOLD", 0.28)
        if buy_pct > threshold:
            final = BUY
        elif sell_pct > threshold:
            final = SELL
        else:
            final = HOLD

        return {"signal": final, "votes": votes, "details": details,
                "buy_pct": round(buy_pct * 100, 1), "sell_pct": round(sell_pct * 100, 1)}

    # ------------------------------------------------------------------
    # Learning — update scores after a trade closes
    # ------------------------------------------------------------------

    def record_trade_result(self, strategy_name: str, pnl_pct: float):
        """Call this after each closed trade to update strategy scores."""
        if strategy_name not in self._scores:
            self._scores[strategy_name] = {"weight": 1.0, "trades": 0, "wins": 0,
                                            "total_pnl": 0.0, "win_rate": 0.0}
        s = self._scores[strategy_name]
        s["trades"] += 1
        if pnl_pct > 0:
            s["wins"] += 1
        s["total_pnl"] = round(s["total_pnl"] + pnl_pct, 4)
        s["win_rate"] = round(s["wins"] / s["trades"] * 100, 1)

        # Recalculate all weights after every 5 trades
        total_trades = sum(v["trades"] for v in self._scores.values())
        if total_trades % 5 == 0:
            self._recalculate_weights()

        self._save_scores()
        logger.info("Strategy %s updated: WR=%.1f%% trades=%d avg_pnl=%.2f%%",
                    strategy_name, s["win_rate"], s["trades"],
                    s["total_pnl"] / s["trades"])

    def _recalculate_weights(self):
        """
        Assign weights based on win rate and average PnL.
        Strategies with 0 trades keep weight=1.0.
        Minimum weight=0.3 so no strategy gets completely ignored early on.
        """
        for name, s in self._scores.items():
            if s["trades"] < 3:
                s["weight"] = 1.0
                continue
            wr_score  = s["win_rate"] / 100          # 0..1
            pnl_score = max(0, s["total_pnl"] / s["trades"] / 4)  # normalize to ~0..1
            raw = (wr_score * 0.6 + pnl_score * 0.4) * 2  # scale to ~0..2
            s["weight"] = round(max(0.3, raw), 3)

        logger.info("Strategy weights updated: %s",
                    {n: v["weight"] for n, v in self._scores.items()})

    def get_scores(self) -> dict:
        return dict(self._scores)

    def best_strategy(self) -> str:
        ranked = sorted(self._scores.items(),
                        key=lambda x: x[1].get("total_pnl", 0), reverse=True)
        return ranked[0][0] if ranked else "RSI_MACD"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_scores(self):
        os.makedirs(os.path.dirname(SCORES_FILE), exist_ok=True)
        dir_ = os.path.dirname(os.path.abspath(SCORES_FILE))
        with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                         suffix=".tmp", encoding="utf-8") as tf:
            json.dump(self._scores, tf, indent=2)
            tmp_path = tf.name
        os.replace(tmp_path, SCORES_FILE)

    def _load_scores(self) -> dict:
        if os.path.exists(SCORES_FILE):
            try:
                with open(SCORES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return _default_scores(self.strategies)
