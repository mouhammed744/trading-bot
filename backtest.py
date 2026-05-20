#!/usr/bin/env python3
"""
Backtest — simulate the strategy on historical Binance klines.

Usage:
    python backtest.py --symbol BTCUSDT --interval 1h --limit 1000
    python backtest.py --symbol BTCUSDT --interval 15m --limit 500 --plot
"""

import argparse
import sys
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd
from binance.client import Client

# Bootstrap config (does not require real API keys for public endpoints)
from bot import config
from bot.strategy import compute_indicators, SIGNAL_BUY, SIGNAL_SELL, SIGNAL_HOLD

logging.basicConfig(level=logging.WARNING)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    entry_idx: int
    entry_price: float
    exit_idx: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""

    @property
    def pnl_pct(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) / self.entry_price * 100

    @property
    def is_winner(self) -> bool:
        return self.pnl_pct > 0


@dataclass
class BacktestResult:
    trades: List[Trade] = field(default_factory=list)
    initial_capital: float = 10_000.0
    symbol: str = ""
    interval: str = ""

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def closed_trades(self) -> List[Trade]:
        return [t for t in self.trades if t.exit_price is not None]

    @property
    def win_rate(self) -> float:
        closed = self.closed_trades
        if not closed:
            return 0.0
        return sum(1 for t in closed if t.is_winner) / len(closed) * 100

    @property
    def total_pnl_pct(self) -> float:
        return sum(t.pnl_pct for t in self.closed_trades)

    @property
    def final_capital(self) -> float:
        capital = self.initial_capital
        for t in self.closed_trades:
            capital *= 1 + t.pnl_pct / 100
        return capital

    @property
    def max_drawdown_pct(self) -> float:
        """Peak-to-trough drawdown across all closed trades (sequential)."""
        capital = self.initial_capital
        peak = capital
        max_dd = 0.0
        for t in self.closed_trades:
            capital *= 1 + t.pnl_pct / 100
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak * 100
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def avg_pnl_pct(self) -> float:
        closed = self.closed_trades
        return self.total_pnl_pct / len(closed) if closed else 0.0

    def summary(self) -> str:
        lines = [
            "",
            "=" * 55,
            f"  BACKTEST RESULTS — {self.symbol} {self.interval}",
            "=" * 55,
            f"  Total trades     : {self.n_trades}",
            f"  Closed trades    : {len(self.closed_trades)}",
            f"  Win rate         : {self.win_rate:.1f}%",
            f"  Avg PnL / trade  : {self.avg_pnl_pct:+.2f}%",
            f"  Total PnL        : {self.total_pnl_pct:+.2f}%",
            f"  Max drawdown     : {self.max_drawdown_pct:.2f}%",
            f"  Initial capital  : ${self.initial_capital:,.2f}",
            f"  Final capital    : ${self.final_capital:,.2f}",
            f"  Net profit       : ${self.final_capital - self.initial_capital:+,.2f}",
            "=" * 55,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fetch data
# ---------------------------------------------------------------------------

def fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    # Public endpoint — no API key required for klines
    client = Client("", "")
    raw = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(raw, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "num_trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("open_time", inplace=True)
    return df


# ---------------------------------------------------------------------------
# Simulation engine
# ---------------------------------------------------------------------------

def _signal_at(df_ind: pd.DataFrame, i: int, rsi_buy: float = 30, rsi_sell: float = 70) -> str:
    """Determine signal at index i using rows [0..i]."""
    if i < 5:
        return SIGNAL_HOLD

    prev = df_ind.iloc[i - 1]
    curr = df_ind.iloc[i]

    any_nan = any(
        pd.isna(curr[c])
        for c in ("rsi", "macd_diff", "ema_short", "ema_long", "volume_ma")
    )
    if any_nan:
        return SIGNAL_HOLD

    rsi = curr["rsi"]
    ema_short = curr["ema_short"]
    ema_long = curr["ema_long"]
    volume = curr["volume"]
    volume_ma = curr["volume_ma"]
    macd_diff = curr["macd_diff"]
    prev_macd_diff = prev["macd_diff"]

    # RSI was oversold in the last 5 candles
    recent_rsi_min = float(df_ind["rsi"].iloc[max(0, i - 5):i].min())

    bullish_cross = prev_macd_diff < 0 and macd_diff >= 0
    bearish_cross = prev_macd_diff > 0 and macd_diff <= 0

    prev_gap = float(prev["ema_long"] - prev["ema_short"])
    curr_gap = float(ema_long - ema_short)
    ema_ok = (ema_short > ema_long) or (curr_gap < prev_gap)

    if recent_rsi_min < rsi_buy and bullish_cross and ema_ok and volume > volume_ma:
        return SIGNAL_BUY
    if rsi > rsi_sell and bearish_cross and ema_short < ema_long:
        return SIGNAL_SELL
    return SIGNAL_HOLD


def run_backtest(
    df: pd.DataFrame,
    stop_loss_pct: float = config.STOP_LOSS_PCT,
    take_profit_pct: float = config.TAKE_PROFIT_PCT,
    initial_capital: float = 10_000.0,
    rsi_buy: float = 30,
    rsi_sell: float = 70,
) -> BacktestResult:
    df_ind = compute_indicators(df)
    result = BacktestResult(initial_capital=initial_capital)
    active_trade: Optional[Trade] = None

    for i in range(len(df_ind)):
        close = float(df_ind.iloc[i]["close"])

        # --- Check SL / TP on open trade ---
        if active_trade is not None:
            sl = active_trade.entry_price * (1 - stop_loss_pct / 100)
            tp = active_trade.entry_price * (1 + take_profit_pct / 100)
            low = float(df_ind.iloc[i]["low"])
            high = float(df_ind.iloc[i]["high"])

            if low <= sl:
                active_trade.exit_idx = i
                active_trade.exit_price = sl
                active_trade.exit_reason = "STOP_LOSS"
                result.trades.append(active_trade)
                active_trade = None
                continue

            if high >= tp:
                active_trade.exit_idx = i
                active_trade.exit_price = tp
                active_trade.exit_reason = "TAKE_PROFIT"
                result.trades.append(active_trade)
                active_trade = None
                continue

        # --- Strategy signal ---
        signal = _signal_at(df_ind, i, rsi_buy=rsi_buy, rsi_sell=rsi_sell)

        if signal == SIGNAL_BUY and active_trade is None:
            active_trade = Trade(entry_idx=i, entry_price=close)

        elif signal == SIGNAL_SELL and active_trade is not None:
            active_trade.exit_idx = i
            active_trade.exit_price = close
            active_trade.exit_reason = "SIGNAL"
            result.trades.append(active_trade)
            active_trade = None

    # Close any still-open trade at last price
    if active_trade is not None:
        last_close = float(df_ind.iloc[-1]["close"])
        active_trade.exit_idx = len(df_ind) - 1
        active_trade.exit_price = last_close
        active_trade.exit_reason = "END_OF_DATA"
        result.trades.append(active_trade)

    return result


# ---------------------------------------------------------------------------
# Trade log table
# ---------------------------------------------------------------------------

def print_trade_log(result: BacktestResult, df: pd.DataFrame):
    if not result.trades:
        print("No trades executed.")
        return

    print("\n  TRADE LOG")
    print(f"  {'#':<4} {'Entry Date':<22} {'Entry $':>10} {'Exit $':>10} {'PnL%':>8} {'Reason':<15}")
    print("  " + "-" * 74)

    for idx, t in enumerate(result.trades, 1):
        entry_date = str(df.index[t.entry_idx])[:19]
        pnl_str = f"{t.pnl_pct:+.2f}%"
        print(
            f"  {idx:<4} {entry_date:<22} {t.entry_price:>10.2f} "
            f"{t.exit_price or 0:>10.2f} {pnl_str:>8} {t.exit_reason:<15}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Backtest trading strategy on Binance klines")
    parser.add_argument("--symbol", default=config.SYMBOL, help="Trading pair (default: %(default)s)")
    parser.add_argument("--interval", default=config.INTERVAL, help="Kline interval (default: %(default)s)")
    parser.add_argument("--limit", type=int, default=500, help="Number of candles (default: %(default)s)")
    parser.add_argument("--capital", type=float, default=10_000.0, help="Initial capital in USD (default: %(default)s)")
    parser.add_argument("--sl", type=float, default=config.STOP_LOSS_PCT, help="Stop-loss %% (default: %(default)s)")
    parser.add_argument("--tp", type=float, default=config.TAKE_PROFIT_PCT, help="Take-profit %% (default: %(default)s)")
    parser.add_argument("--rsi-buy", type=float, default=30, help="RSI threshold for BUY signal (default: 30)")
    parser.add_argument("--rsi-sell", type=float, default=70, help="RSI threshold for SELL signal (default: 70)")
    parser.add_argument("--log", action="store_true", help="Print individual trade log")
    return parser.parse_args()


def main():
    args = parse_args()

    print(f"\nFetching {args.limit} {args.interval} candles for {args.symbol}...", end=" ", flush=True)
    try:
        df = fetch_klines(args.symbol, args.interval, args.limit)
    except Exception as exc:
        print(f"\nError fetching data: {exc}")
        sys.exit(1)
    print(f"OK ({len(df)} rows)")

    result = run_backtest(df, args.sl, args.tp, args.capital, args.rsi_buy, args.rsi_sell)
    result.symbol = args.symbol
    result.interval = args.interval

    if args.log:
        print_trade_log(result, df)

    print(result.summary())


if __name__ == "__main__":
    main()
