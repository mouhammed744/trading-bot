import json
import logging
import os
from dataclasses import dataclass, asdict
from typing import Optional
from bot.config import POSITIONS_FILE, STOP_LOSS_PCT, TAKE_PROFIT_PCT

logger = logging.getLogger("trading_bot.risk")


@dataclass
class Position:
    symbol: str
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    side: str = "LONG"
    highest_price: float = 0.0  # pour le trailing stop loss

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(**data)


class RiskManager:
    def __init__(
        self,
        stop_loss_pct: float = STOP_LOSS_PCT,
        take_profit_pct: float = TAKE_PROFIT_PCT,
        positions_file: str = POSITIONS_FILE,
    ):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.positions_file = positions_file
        self.position: Optional[Position] = self._load_position()

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------

    def open_position(self, symbol: str, entry_price: float, quantity: float,
                      sl_pct: float = None, tp_pct: float = None) -> Position:
        sl_pct = sl_pct if sl_pct is not None else self.stop_loss_pct
        tp_pct = tp_pct if tp_pct is not None else self.take_profit_pct
        stop_loss = entry_price * (1 - sl_pct / 100)
        take_profit = entry_price * (1 + tp_pct / 100)
        self.position = Position(
            symbol=symbol,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=round(stop_loss, 8),
            take_profit=round(take_profit, 8),
        )
        self._save_position()
        logger.info(
            "Position opened: entry=%.4f SL=%.4f TP=%.4f qty=%s",
            entry_price, stop_loss, take_profit, quantity,
        )
        return self.position

    def update_trailing_sl(self, current_price: float, trailing_pct: float) -> bool:
        """Monte le SL si le prix monte. Retourne True si le SL a ete mis a jour."""
        if not self.position:
            return False
        if self.position.highest_price == 0.0:
            self.position.highest_price = self.position.entry_price
        if current_price > self.position.highest_price:
            self.position.highest_price = current_price
            new_sl = round(current_price * (1 - trailing_pct / 100), 8)
            if new_sl > self.position.stop_loss:
                old_sl = self.position.stop_loss
                self.position.stop_loss = new_sl
                self._save_position()
                logger.info(
                    "Trailing SL mis a jour: %.4f -> %.4f (prix max=%.4f)",
                    old_sl, new_sl, current_price,
                )
                return True
        return False

    def close_position(self) -> Optional[Position]:
        pos = self.position
        self.position = None
        self._save_position()
        if pos:
            logger.info("Position closed: entry=%.4f", pos.entry_price)
        return pos

    def has_position(self) -> bool:
        return self.position is not None

    # ------------------------------------------------------------------
    # SL / TP checks
    # ------------------------------------------------------------------

    def should_stop_loss(self, current_price: float) -> bool:
        if not self.position:
            return False
        triggered = current_price <= self.position.stop_loss
        if triggered:
            logger.warning(
                "Stop-loss triggered: current=%.4f SL=%.4f",
                current_price, self.position.stop_loss,
            )
        return triggered

    def should_take_profit(self, current_price: float) -> bool:
        if not self.position:
            return False
        triggered = current_price >= self.position.take_profit
        if triggered:
            logger.info(
                "Take-profit triggered: current=%.4f TP=%.4f",
                current_price, self.position.take_profit,
            )
        return triggered

    def pnl_pct(self, current_price: float) -> float:
        """Current unrealised PnL as a percentage."""
        if not self.position:
            return 0.0
        return (current_price - self.position.entry_price) / self.position.entry_price * 100

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_position(self):
        data = self.position.to_dict() if self.position else None
        with open(self.positions_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _load_position(self) -> Optional[Position]:
        if not os.path.exists(self.positions_file):
            return None
        try:
            with open(self.positions_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data is None:
                return None
            pos = Position.from_dict(data)
            logger.info("Loaded existing position: %s @ %.4f", pos.symbol, pos.entry_price)
            return pos
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Could not load position file: %s", exc)
            return None
