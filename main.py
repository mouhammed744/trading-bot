#!/usr/bin/env python3
"""
Binance Trading Bot v2 — multi-strategy, adaptive, with weekly reports.

Usage:
    python main.py --mode testnet
    python main.py --mode live
    python main.py --mode testnet --report   # generate report now
"""

import argparse
import sys
import time
import logging
import os
from datetime import datetime, timezone, timedelta

from bot import config
from bot.trader import Trader
from bot.risk_manager import RiskManager
from bot.strategy_manager import StrategyManager
from bot.trade_journal import TradeJournal
from bot.optimizer import load_best_params, should_optimize, optimize
from bot.reporter import generate_weekly_report
from bot.market_analyzer import MarketAnalyzer

POLL_SECONDS = 60
REPORT_INTERVAL_DAYS = 7


def _multi_tf_bullish(trader: "Trader", logger) -> bool:
    """Verifie que la tendance est haussiere sur 1h ET/OU 4h avant d'acheter."""
    bullish = 0
    for interval, limit in [("1h", 100), ("4h", 50)]:
        try:
            df = trader.get_klines(limit=limit, interval=interval)
            close = df["close"]
            ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
            price = float(close.iloc[-1])
            if price > ema50:
                bullish += 1
                logger.debug("Multi-TF %s: haussier (%.2f > EMA50 %.2f)", interval, price, ema50)
            else:
                logger.debug("Multi-TF %s: baissier (%.2f < EMA50 %.2f)", interval, price, ema50)
        except Exception as exc:
            logger.warning("Multi-TF %s indisponible: %s — ignore", interval, exc)
            bullish += 1  # ne pas bloquer si l'API echoue
    ok = bullish >= 1  # au moins 1 des 2 timeframes haussier
    logger.info("Multi-TF: %d/2 haussiers — %s", bullish, "OK" if ok else "BLOQUE")
    return ok


def parse_args():
    p = argparse.ArgumentParser(description="Binance Trading Bot v2")
    p.add_argument("--mode", choices=["testnet", "live"], default="testnet")
    p.add_argument("--poll", type=int, default=POLL_SECONDS)
    p.add_argument("--report", action="store_true", help="Generate weekly report and exit")
    p.add_argument("--analyze", action="store_true", help="Analyser le marche et afficher une recommandation, puis quitter")
    return p.parse_args()


def confirm_live_mode() -> bool:
    print("\n" + "=" * 60)
    print("  AVERTISSEMENT: Mode LIVE — argent reel engage.")
    print("  Toute perte est definitive.")
    print("=" * 60)
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


def run_bot(mode: str, poll_seconds: int, report_only: bool = False, analyze_only: bool = False):
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    logger = config.setup_logging()
    logger.info("=== Trading Bot v2 demarrage — mode %s ===", mode.upper())

    errors = config.validate_config()
    if errors:
        for e in errors:
            logger.error("Config: %s", e)
        sys.exit(1)

    testnet = (mode == "testnet")
    if not testnet and not confirm_live_mode():
        print("Annule.")
        sys.exit(0)

    # Components
    trader          = Trader(testnet=testnet)
    risk_mgr        = RiskManager()
    strategy_mgr    = StrategyManager()
    journal         = TradeJournal()
    analyzer        = MarketAnalyzer()
    sl_pct, tp_pct  = load_best_params()

    if not trader.ping():
        logger.error("Impossible de se connecter a Binance.")
        sys.exit(1)

    logger.info("Connecte. SL=%.1f%% TP=%.1f%%  strategies=%s",
                sl_pct, tp_pct, [s.name for s in strategy_mgr.strategies])

    # Report-only mode
    if report_only:
        _do_report(journal, strategy_mgr, sl_pct, tp_pct, logger)
        return

    # Analyze-only mode
    if analyze_only:
        df = trader.get_klines(limit=300)
        balance = trader.get_account_balance("USDT")
        analysis = analyzer.analyze(df)
        analyzer.print_report(analysis, balance_usdt=balance)
        return

    closed_trades_count = len(journal.closed_trades())

    while True:
        try:
            current_price = trader.get_ticker_price()

            # --- Weekly report check ---
            if datetime.now(timezone.utc) - _last_report_time() >= timedelta(days=REPORT_INTERVAL_DAYS):
                _do_report(journal, strategy_mgr, sl_pct, tp_pct, logger)

            # --- SL / TP check on open position ---
            open_trade = journal.get_open_trade()
            if risk_mgr.has_position() and open_trade:
                # Trailing SL — monte le SL quand le prix monte
                if config.TRAILING_SL_ENABLED:
                    risk_mgr.update_trailing_sl(current_price, config.TRAILING_SL_PCT)

                pnl = risk_mgr.pnl_pct(current_price)
                logger.info(
                    "Position ouverte | prix=%.2f PnL=%+.2f%% SL=%.2f TP=%.2f",
                    current_price, pnl,
                    risk_mgr.position.stop_loss, risk_mgr.position.take_profit,
                )

                exit_reason = None
                if risk_mgr.should_stop_loss(current_price):
                    exit_reason = "STOP_LOSS"
                    logger.warning("STOP-LOSS declenche")
                elif risk_mgr.should_take_profit(current_price):
                    exit_reason = "TAKE_PROFIT"
                    logger.info("TAKE-PROFIT atteint")

                if exit_reason:
                    sell_qty = risk_mgr.position.quantity
                    trader.place_market_sell(quantity=sell_qty)
                    journal.close_trade(open_trade.id, current_price, exit_reason)
                    strategy_mgr.record_trade_result(open_trade.strategy, pnl)
                    risk_mgr.close_position()
                    closed_trades_count += 1

                    # Auto-optimize after N trades
                    if should_optimize(closed_trades_count):
                        logger.info("Lancement de l'optimisation des parametres...")
                        df = trader.get_klines(limit=500)
                        new_sl, new_tp = optimize(df, sl_pct, tp_pct)
                        if new_sl != sl_pct or new_tp != tp_pct:
                            logger.info("Nouveaux parametres: SL=%.1f%% TP=%.1f%%", new_sl, new_tp)
                            sl_pct, tp_pct = new_sl, new_tp
                            risk_mgr.stop_loss_pct = sl_pct
                            risk_mgr.take_profit_pct = tp_pct

                    time.sleep(poll_seconds)
                    continue

            # --- Strategy signal ---
            if not risk_mgr.has_position():
                df = trader.get_klines(limit=200)
                result = strategy_mgr.get_signal(df)
                signal = result["signal"]

                logger.info(
                    "Signal: %s | BUY=%.0f%% SELL=%.0f%% | %s",
                    signal,
                    result["buy_pct"],
                    result["sell_pct"],
                    {k: v.get("signal") for k, v in result["details"].items()},
                )

                if signal == "BUY":
                    # Analyse du marche avant d'acheter
                    market = analyzer.analyze(df)
                    balance = trader.get_account_balance("USDT")
                    analyzer.print_report(market, balance_usdt=balance)

                    if market["recommendation"] == "EVITER":
                        logger.info("Signal BUY ignore — analyse marche defavorable (%s)", market["trend"])
                    elif not _multi_tf_bullish(trader, logger):
                        logger.info("Signal BUY ignore — tendance 1h/4h defavorable")
                    elif balance < config.MIN_USDT_BALANCE:
                        logger.warning(
                            "SIGNAL D'ACHAT DETECTE mais solde insuffisant (%.2f USDT). "
                            "Rechargez votre portefeuille Binance avec au moins %.2f USDT.",
                            balance, config.MIN_USDT_BALANCE
                        )
                        print(f"\n  !!! SIGNAL D'ACHAT — rechargez votre portefeuille !")
                        print(f"  !!! Solde actuel : {balance:.2f} USDT")
                        print(f"  !!! Minimum requis : {config.MIN_USDT_BALANCE:.2f} USDT\n")
                    else:
                        # Quantite basee sur 90% du solde disponible
                        qty = round((balance * config.TRADE_BALANCE_PCT) / current_price, 5)

                        triggering = next(
                            (k for k, v in result["details"].items() if v.get("signal") == "BUY"),
                            strategy_mgr.best_strategy()
                        )
                        logger.info(
                            "BUY confirme — solde=%.2f USDT qty=%.5f via %s",
                            balance, qty, triggering
                        )
                        order = trader.place_market_buy(quantity=qty)
                        fill_price = trader.get_filled_price(order) or current_price
                        risk_mgr.open_position(config.SYMBOL, fill_price, qty,
                                               sl_pct=sl_pct, tp_pct=tp_pct)
                        journal.open_trade(
                            symbol=config.SYMBOL,
                            strategy=triggering,
                            entry_price=fill_price,
                            quantity=qty,
                            stop_loss=risk_mgr.position.stop_loss,
                            take_profit=risk_mgr.position.take_profit,
                        )
                        logger.info("BUY execute via %s @ %.2f", triggering, fill_price)

            elif risk_mgr.has_position() and open_trade:
                # Check SELL signal to close early
                df = trader.get_klines(limit=200)
                result = strategy_mgr.get_signal(df)
                if result["signal"] == "SELL":
                    pnl = risk_mgr.pnl_pct(current_price)
                    sell_qty = risk_mgr.position.quantity
                    trader.place_market_sell(quantity=sell_qty)
                    journal.close_trade(open_trade.id, current_price, "SIGNAL_SELL")
                    strategy_mgr.record_trade_result(open_trade.strategy, pnl)
                    risk_mgr.close_position()
                    closed_trades_count += 1
                    logger.info("SELL signal — position fermee @ %.2f PnL=%+.2f%%",
                                current_price, pnl)

        except KeyboardInterrupt:
            logger.info("Arret par l'utilisateur.")
            break
        except Exception as exc:
            logger.error("Erreur: %s", exc, exc_info=True)

        time.sleep(poll_seconds)


if __name__ == "__main__":
    args = parse_args()
    run_bot(args.mode, args.poll, report_only=args.report, analyze_only=args.analyze)
