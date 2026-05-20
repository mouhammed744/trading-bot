"""
Persistent trade journal — logs every opened/closed trade to data/trades.json.
"""
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Optional, List

JOURNAL_FILE = os.path.join("data", "trades.json")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class TradeRecord:
    def __init__(self, symbol: str, strategy: str, entry_price: float,
                 quantity: float, stop_loss: float, take_profit: float):
        self.id = str(uuid.uuid4())[:8]
        self.symbol = symbol
        self.strategy = strategy
        self.entry_price = entry_price
        self.quantity = quantity
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.entry_time = _now()
        self.exit_price: Optional[float] = None
        self.exit_time: Optional[str] = None
        self.exit_reason: Optional[str] = None
        self.pnl_pct: Optional[float] = None
        self.pnl_usd: Optional[float] = None

    def close(self, exit_price: float, reason: str):
        self.exit_price = exit_price
        self.exit_time = _now()
        self.exit_reason = reason
        self.pnl_pct = round((exit_price - self.entry_price) / self.entry_price * 100, 4)
        self.pnl_usd = round((exit_price - self.entry_price) * self.quantity, 4)

    @property
    def is_closed(self) -> bool:
        return self.exit_price is not None

    @property
    def is_winner(self) -> bool:
        return (self.pnl_pct or 0) > 0

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "TradeRecord":
        t = cls.__new__(cls)
        t.__dict__.update(d)
        return t


class TradeJournal:
    def __init__(self, path: str = JOURNAL_FILE):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._trades: List[TradeRecord] = self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_trade(self, symbol: str, strategy: str, entry_price: float,
                   quantity: float, stop_loss: float, take_profit: float) -> TradeRecord:
        t = TradeRecord(symbol, strategy, entry_price, quantity, stop_loss, take_profit)
        self._trades.append(t)
        self._save()
        return t

    def close_trade(self, trade_id: str, exit_price: float, reason: str) -> Optional[TradeRecord]:
        for t in self._trades:
            if t.id == trade_id and not t.is_closed:
                t.close(exit_price, reason)
                self._save()
                return t
        return None

    def get_open_trade(self) -> Optional[TradeRecord]:
        for t in self._trades:
            if not t.is_closed:
                return t
        return None

    def closed_trades(self, since: Optional[str] = None) -> List[TradeRecord]:
        trades = [t for t in self._trades if t.is_closed]
        if since:
            trades = [t for t in trades if t.exit_time >= since]
        return trades

    def all_trades(self) -> List[TradeRecord]:
        return list(self._trades)

    def stats(self, since: Optional[str] = None) -> dict:
        trades = self.closed_trades(since)
        if not trades:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                    "total_pnl_pct": 0, "total_pnl_usd": 0, "avg_pnl_pct": 0,
                    "best_pct": 0, "worst_pct": 0}
        wins = [t for t in trades if t.is_winner]
        losses = [t for t in trades if not t.is_winner]
        pnls = [t.pnl_pct for t in trades]
        return {
            "total": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "total_pnl_pct": round(sum(pnls), 2),
            "total_pnl_usd": round(sum(t.pnl_usd or 0.0 for t in trades), 2),
            "avg_pnl_pct": round(sum(pnls) / len(pnls), 2),
            "best_pct": round(max(pnls), 2),
            "worst_pct": round(min(pnls), 2),
        }

    def stats_by_strategy(self) -> dict:
        result = {}
        for t in self.closed_trades():
            s = t.strategy
            if s not in result:
                result[s] = []
            result[s].append(t)
        out = {}
        for s, trades in result.items():
            wins = sum(1 for t in trades if t.is_winner)
            pnls = [t.pnl_pct for t in trades]
            out[s] = {
                "total": len(trades),
                "wins": wins,
                "win_rate": round(wins / len(trades) * 100, 1),
                "avg_pnl_pct": round(sum(pnls) / len(pnls), 2),
                "total_pnl_pct": round(sum(pnls), 2),
            }
        return out

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self):
        dir_ = os.path.dirname(os.path.abspath(self.path))
        with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                         suffix=".tmp", encoding="utf-8") as tf:
            json.dump([t.to_dict() for t in self._trades], tf, indent=2)
            tmp_path = tf.name
        os.replace(tmp_path, self.path)

    def _load(self) -> List[TradeRecord]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return [TradeRecord.from_dict(d) for d in json.load(f)]
        except Exception:
            return []
