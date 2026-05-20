"""
Gestionnaire de portefeuille multi-positions.
Gere jusqu'a MAX_POSITIONS positions ouvertes en meme temps.
"""
import json
import logging
import os
import tempfile
from dataclasses import dataclass, asdict
from typing import Dict, Optional

logger = logging.getLogger("trading_bot.portfolio")

PORTFOLIO_FILE = os.path.join("data", "portfolio.json")


@dataclass
class PortfolioPosition:
    symbol: str
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    strategy: str
    entry_time: str
    highest_price: float = 0.0
    side: str = "LONG"

    @property
    def pnl_pct(self, current_price: float = 0) -> float:
        if current_price == 0:
            return 0.0
        return (current_price - self.entry_price) / self.entry_price * 100

    def calc_pnl_pct(self, current_price: float) -> float:
        return (current_price - self.entry_price) / self.entry_price * 100

    def should_stop_loss(self, price: float) -> bool:
        return price <= self.stop_loss

    def should_take_profit(self, price: float) -> bool:
        return price >= self.take_profit

    def update_trailing_sl(self, price: float, trailing_pct: float) -> bool:
        if self.highest_price == 0.0:
            self.highest_price = self.entry_price
        if price > self.highest_price:
            self.highest_price = price
            new_sl = round(price * (1 - trailing_pct / 100), 8)
            if new_sl > self.stop_loss:
                old = self.stop_loss
                self.stop_loss = new_sl
                logger.info("%s Trailing SL: %.6f -> %.6f", self.symbol, old, new_sl)
                return True
        return False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PortfolioPosition":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class Portfolio:
    def __init__(self, max_positions: int = 10):
        self.max_positions = max_positions
        self._positions: Dict[str, PortfolioPosition] = {}
        os.makedirs("data", exist_ok=True)
        self._load()

    # ------------------------------------------------------------------

    def can_open(self) -> bool:
        return len(self._positions) < self.max_positions

    def has_position(self, symbol: str) -> bool:
        return symbol in self._positions

    def get_position(self, symbol: str) -> Optional[PortfolioPosition]:
        return self._positions.get(symbol)

    def all_positions(self) -> Dict[str, PortfolioPosition]:
        return dict(self._positions)

    def count(self) -> int:
        return len(self._positions)

    def open_position(self, symbol: str, entry_price: float, quantity: float,
                      sl_pct: float, tp_pct: float, strategy: str,
                      entry_time: str) -> PortfolioPosition:
        pos = PortfolioPosition(
            symbol=symbol,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=round(entry_price * (1 - sl_pct / 100), 8),
            take_profit=round(entry_price * (1 + tp_pct / 100), 8),
            strategy=strategy,
            entry_time=entry_time,
            highest_price=entry_price,
        )
        self._positions[symbol] = pos
        self._save()
        logger.info(
            "Position ouverte: %s @ %.6f qty=%.6f SL=%.6f TP=%.6f via %s",
            symbol, entry_price, quantity, pos.stop_loss, pos.take_profit, strategy,
        )
        return pos

    def close_position(self, symbol: str) -> Optional[PortfolioPosition]:
        pos = self._positions.pop(symbol, None)
        self._save()
        if pos:
            logger.info("Position fermee: %s @ entry=%.6f", symbol, pos.entry_price)
        return pos

    def position_usdt_value(self, symbol: str, current_price: float) -> float:
        pos = self._positions.get(symbol)
        if not pos:
            return 0.0
        return pos.quantity * current_price

    # ------------------------------------------------------------------

    def _save(self):
        data = {sym: pos.to_dict() for sym, pos in self._positions.items()}
        dir_ = os.path.dirname(os.path.abspath(PORTFOLIO_FILE))
        with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                         suffix=".tmp", encoding="utf-8") as tf:
            json.dump(data, tf, indent=2)
            tmp_path = tf.name
        os.replace(tmp_path, PORTFOLIO_FILE)

    def _load(self):
        if not os.path.exists(PORTFOLIO_FILE):
            return
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for sym, d in data.items():
                self._positions[sym] = PortfolioPosition.from_dict(d)
            if self._positions:
                logger.info("Portfolio charge: %d positions ouvertes", len(self._positions))
        except Exception as exc:
            logger.warning("Impossible de charger le portfolio: %s", exc)
