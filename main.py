#!/usr/bin/env python3
"""
Binance Trading Bot v3 — multi-crypto, multi-strategy, adaptatif.

Usage:
    python main.py --mode testnet
    python main.py --mode live
    python main.py --mode live --analyze
    python main.py --mode live --report
"""

import argparse
import sys
import time
import logging
import os
from datetime import datetime, timezone, timedelta

from bot import config
from bot.trader import Trader
from bot.strategy_manager import StrategyManager
from bot.trade_journal import TradeJournal
from bot.optimizer import load_best_params, should_optimize, optimize
from bot.reporter import generate_weekly_report
from bot.market_analyzer import MarketAnalyzer
from bot.scanner import Scanner
from bot.portfolio import Portfolio

POLL_SECONDS = 60
REPORT_INTERVAL_DAYS = 7


def parse_args():
    p = argparse.ArgumentParser(description="Binance Trading Bot v3 — Multi-Crypto")
    p.add_argument("--mode", choices=["testnet", "live"], default="testnet")
    p.add_argument("--poll", type=int, default=POLL_SECONDS)
    p.add_argument("--report", action="store_true")
    p.add_argument("--analyze", action="store_true", help="Analyser le marche puis quitter")
    return p.parse_args()


def confirm_live_mode() -> bool:
    print("\n" + "=" * 62)
    print("  AVERTISSEMENT: Mode LIVE — argent reel engage.")
    print("  Mode MULTI-CRYPTO — jusqu'a {} positions simultanees.".format(config.MAX_POSITIONS))
    print("  Toute perte est definitive.")
    print("=" * 62)
    return input("Tape 'YES I UNDERSTAND' pour continuer: ").strip() == "YES I UNDERSTAND"


def _last_report_time() -> datetime:
    path = os.path.join("data", "last_report.txt")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return datetime.fromisoformat(f.read().strip())
        except Exception:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _save_report_time():
    os.makedirs("data", exist_ok=True)
    with open(os.path.join("data", "last_report.txt"), "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())


def _do_report(journal, strategy_manager, sl, tp, logger):
    scores = strategy_manager.get_scores()
    report = generate_weekly_report(
        journal, scores, sl, tp, config.SYMBOL, config.INTERVAL
    )
    print(report)
    _save_report_time()
    logger.info("Rapport hebdomadaire genere.")


def _multi_tf_bullish(trader: Trader, symbol: str, logger) -> bool:
    """Verifie tendance haussiere sur 1h et 4h avant d'acheter."""
    bullish = 0
    for interval, limit in [("1h", 100), ("4h", 50)]:
        try:
            df = trader.get_klines(limit=limit, interval=interval, symbol=symbol)
            close = df["close"]
            ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
            price = float(close.iloc[-1])
            if price > ema50:
                bullish += 1
        except Exception as exc:
            logger.debug("Multi-TF %s %s: %s", symbol, interval, exc)
            bullish += 1
    return bullish >= 1


def _calc_quantity(balance_usdt: float, price: float, n_slots: int) -> float:
    if price <= 0:
        raise ValueError(f"Prix invalide: {price}")
    if balance_usdt <= 0:
        raise ValueError(f"Balance invalide: {balance_usdt}")
    per_trade = (balance_usdt * config.TRADE_BALANCE_PCT) / max(n_slots, 1)
    qty = per_trade / price
    return round(qty, 6)


def _open_trade(trader, portfolio, journal, strategy_mgr, symbol, signal_result,
                balance_usdt, sl_pct, tp_pct, logger):
    if portfolio.has_position(symbol) or not portfolio.can_open():
        return
    if not _multi_tf_bullish(trader, symbol, logger):
        logger.info("%s: tendance superieure defavorable — ignore", symbol)
        return
    try:
        price = trader.get_ticker_price(symbol=symbol)
    except Exception as exc:
        logger.warning("Prix %s indisponible: %s", symbol, exc)
        return

    free_slots = config.MAX_POSITIONS - portfolio.count()
    qty = _calc_quantity(balance_usdt, price, free_slots)

    if qty * price < config.MIN_USDT_BALANCE:
        logger.info("%s: mise trop faible (%.2f USDT) — ignore", symbol, qty * price)
        return

    triggering = next(
        (k for k, v in signal_result["details"].items() if v.get("signal") == "BUY"),
        strategy_mgr.best_strategy()
    )
    try:
        order = trader.place_market_buy(quantity=qty, symbol=symbol)
        fill_price = trader.get_filled_price(order) or price
        entry_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        portfolio.open_position(
            symbol=symbol, entry_price=fill_price, quantity=qty,
            sl_pct=sl_pct, tp_pct=tp_pct, strategy=triggering,
            entry_time=entry_time,
        )
        open_pos = portfolio.get_position(symbol)
        journal.open_trade(
            symbol=symbol, strategy=triggering, entry_price=fill_price,
            quantity=qty, stop_loss=open_pos.stop_loss, take_profit=open_pos.take_profit,
        )
        logger.info(">>> BUY %s @ %.6f qty=%.6f mise=%.2f USDT via %s",
                    symbol, fill_price, qty, qty * fill_price, triggering)
    except Exception as exc:
        logger.error("Erreur BUY %s: %s", symbol, exc)


def _close_trade(trader, portfolio, journal, strategy_mgr, symbol, reason, logger):
    pos = portfolio.get_position(symbol)
    if not pos:
        return
    open_trade = next(
        (t for t in journal.all_trades() if t.symbol == symbol and not t.is_closed),
        None
    )
    try:
        trader.place_market_sell(quantity=pos.quantity, symbol=symbol)
        price = trader.get_ticker_price(symbol=symbol)
        pnl = pos.calc_pnl_pct(price)
        if open_trade:
            journal.close_trade(open_trade.id, price, reason)
            strategy_mgr.record_trade_result(pos.strategy, pnl)
        portfolio.close_position(symbol)
        logger.info(">>> SELL %s @ %.6f PnL=%+.2f%% [%s]", symbol, price, pnl, reason)
    except Exception as exc:
        logger.error("Erreur SELL %s: %s", symbol, exc)


def run_bot(mode: str, poll_seconds: int, report_only: bool = False, analyze_only: bool = False):
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    logger = config.setup_logging()
    logger.info("=== Trading Bot v3 MULTI-CRYPTO — mode %s ===", mode.upper())

    errors = config.validate_config()
    if errors:
        for e in errors:
            logger.error("Config: %s", e)
        sys.exit(1)

    testnet = (mode == "testnet")
    if not testnet and not confirm_live_mode():
        print("Annule.")
        sys.exit(0)

    trader       = Trader(testnet=testnet)
    strategy_mgr = StrategyManager()
    journal      = TradeJournal()
    analyzer     = MarketAnalyzer()
    portfolio    = Portfolio(max_positions=config.MAX_POSITIONS)
    scanner      = Scanner(trader)
    sl_pct, tp_pct = load_best_params()

    if not trader.ping():
        logger.error("Impossible de se connecter a Binance.")
        sys.exit(1)

    logger.info("Connecte. SL=%.1f%% TP=%.1f%% | %d strategies | Max %d positions",
                sl_pct, tp_pct, len(strategy_mgr.strategies), config.MAX_POSITIONS)

    if report_only:
        _do_report(journal, strategy_mgr, sl_pct, tp_pct, logger)
        return

    if analyze_only:
        df = trader.get_klines(limit=300)
        balance = trader.get_account_balance("USDT")
        analysis = analyzer.analyze(df)
        analyzer.print_report(analysis, balance_usdt=balance)
        return

    last_scan_time = 0
    closed_count   = len(journal.closed_trades())

    while True:
        try:
            now = time.time()
            balance_usdt = trader.get_account_balance("USDT")

            # Rapport hebdomadaire
            if datetime.now(timezone.utc) - _last_report_time() >= timedelta(days=REPORT_INTERVAL_DAYS):
                _do_report(journal, strategy_mgr, sl_pct, tp_pct, logger)

            # --- Surveillance des positions ouvertes ---
            for symbol, pos in list(portfolio.all_positions().items()):
                try:
                    price = trader.get_ticker_price(symbol=symbol)

                    if config.TRAILING_SL_ENABLED:
                        if pos.update_trailing_sl(price, config.TRAILING_SL_PCT):
                            portfolio._save()

                    pnl = pos.calc_pnl_pct(price)
                    logger.info("%s | prix=%.6f PnL=%+.2f%% SL=%.6f TP=%.6f",
                                symbol, price, pnl, pos.stop_loss, pos.take_profit)

                    if pos.should_stop_loss(price):
                        _close_trade(trader, portfolio, journal, strategy_mgr,
                                     symbol, "STOP_LOSS", logger)
                        closed_count += 1
                        continue

                    if pos.should_take_profit(price):
                        _close_trade(trader, portfolio, journal, strategy_mgr,
                                     symbol, "TAKE_PROFIT", logger)
                        closed_count += 1
                        continue

                    df = trader.get_klines(limit=200, symbol=symbol)
                    result = strategy_mgr.get_signal(df)
                    if result["signal"] == "SELL":
                        _close_trade(trader, portfolio, journal, strategy_mgr,
                                     symbol, "SIGNAL_SELL", logger)
                        closed_count += 1

                except Exception as exc:
                    logger.error("Erreur surveillance %s: %s", symbol, exc)

            # Auto-optimisation
            if should_optimize(closed_count):
                df = trader.get_klines(limit=500)
                new_sl, new_tp = optimize(df, sl_pct, tp_pct)
                if new_sl != sl_pct or new_tp != tp_pct:
                    sl_pct, tp_pct = new_sl, new_tp
                    logger.info("Optimisation: SL=%.1f%% TP=%.1f%%", sl_pct, tp_pct)

            # --- Scanner multi-crypto ---
            if portfolio.can_open() and (now - last_scan_time) >= config.SCAN_INTERVAL:
                last_scan_time = now
                free = config.MAX_POSITIONS - portfolio.count()
                logger.info("=== SCAN MULTI-CRYPTO | %d slots libres ===", free)

                opportunities = scanner.scan(strategy_mgr, limit=200, interval=config.INTERVAL)
                logger.info("%d opportunites BUY trouvees", len(opportunities))

                for opp in opportunities[:free]:
                    symbol = opp["symbol"]
                    if portfolio.has_position(symbol):
                        continue
                    try:
                        df_opp = trader.get_klines(limit=300, symbol=symbol)
                        market = analyzer.analyze(df_opp)
                        if market["recommendation"] == "EVITER":
                            continue
                    except Exception:
                        continue

                    _open_trade(trader, portfolio, journal, strategy_mgr,
                                symbol, opp, balance_usdt, sl_pct, tp_pct, logger)

            logger.info("Portfolio: %d/%d positions | Solde: %.2f USDT",
                        portfolio.count(), config.MAX_POSITIONS, balance_usdt)

        except KeyboardInterrupt:
            logger.info("Arret. %d positions ouvertes.", portfolio.count())
            break
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.exception("Erreur boucle: %s", exc)
            else:
                logger.error("Erreur boucle: %s — %s", type(exc).__name__, exc)

        time.sleep(poll_seconds)


if __name__ == "__main__":
    args = parse_args()
    run_bot(args.mode, args.poll, report_only=args.report, analyze_only=args.analyze)
