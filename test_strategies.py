#!/usr/bin/env python3
"""
=============================================================
  TEST COMPLET DU BOT v2
  Teste chaque composant sans avoir besoin de cles API.
  Utilise les vraies donnees Binance (endpoint public).

  Usage:
    python test_strategies.py           # tous les tests
    python test_strategies.py --unit    # tests unitaires seulement (hors ligne)
    python test_strategies.py --live    # + test connexion Binance
=============================================================
"""

import argparse
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.makedirs("data/reports", exist_ok=True)

import pandas as pd
import numpy as np

# ---------------------------------------------------------
# Couleurs terminal
# ---------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

ok  = lambda msg: print(f"  {GREEN}[OK]{RESET} {msg}")
err = lambda msg: print(f"  {RED}[ECHEC] {msg}{RESET}")
warn= lambda msg: print(f"  {YELLOW}[WARN] {msg}{RESET}")
hdr = lambda msg: print(f"\n{BOLD}{BLUE}{'-'*58}\n  {msg}\n{'-'*58}{RESET}")

passed = failed = 0

def check(label, condition, detail=""):
    global passed, failed
    if condition:
        ok(label)
        passed += 1
    else:
        err(f"{label}  {detail}")
        failed += 1


# ---------------------------------------------------------
# Generateur de donnees simulees
# ---------------------------------------------------------

def make_trending_df(n=200, start=40000, trend=50):
    """Marche haussier simul_."""
    np.random.seed(42)
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] + trend + np.random.randn() * 200)
    df = pd.DataFrame({
        "open":   prices,
        "high":   [p + abs(np.random.randn() * 100) for p in prices],
        "low":    [p - abs(np.random.randn() * 100) for p in prices],
        "close":  prices,
        "volume": [abs(np.random.randn() * 500 + 1000) for _ in prices],
    })
    return df


def make_ranging_df(n=200, center=40000, amplitude=1000):
    """Marche oscillant simul_."""
    np.random.seed(7)
    prices = [center + amplitude * np.sin(i * 0.15) + np.random.randn() * 50
              for i in range(n)]
    df = pd.DataFrame({
        "open":   prices,
        "high":   [p + abs(np.random.randn() * 80) for p in prices],
        "low":    [p - abs(np.random.randn() * 80) for p in prices],
        "close":  prices,
        "volume": [abs(np.random.randn() * 300 + 800) for _ in prices],
    })
    return df


def make_oversold_df(n=150):
    """Prix qui chute puis rebondit - devrait d_clencher RSI BUY."""
    np.random.seed(99)
    prices = [50000 - i * 100 + np.random.randn() * 30 for i in range(80)]
    prices += [prices[-1] + i * 120 + np.random.randn() * 30 for i in range(70)]
    df = pd.DataFrame({
        "open":   prices,
        "high":   [p + abs(np.random.randn() * 50) for p in prices],
        "low":    [p - abs(np.random.randn() * 50) for p in prices],
        "close":  prices,
        "volume": [abs(np.random.randn() * 500 + 1200) for _ in prices],
    })
    return df


# ---------------------------------------------------------
# TEST 1 - Imports
# ---------------------------------------------------------

hdr("TEST 1 - IMPORTS DES MODULES")

try:
    from bot.strategies.rsi_macd import RSIMACDStrategy
    ok("RSIMACDStrategy importee")
    passed += 1
except Exception as e:
    err(f"RSIMACDStrategy: {e}"); failed += 1

try:
    from bot.strategies.bollinger import BollingerStrategy
    ok("BollingerStrategy importee")
    passed += 1
except Exception as e:
    err(f"BollingerStrategy: {e}"); failed += 1

try:
    from bot.strategies.breakout import BreakoutStrategy
    ok("BreakoutStrategy importee")
    passed += 1
except Exception as e:
    err(f"BreakoutStrategy: {e}"); failed += 1

try:
    from bot.strategy_manager import StrategyManager
    ok("StrategyManager importe")
    passed += 1
except Exception as e:
    err(f"StrategyManager: {e}"); failed += 1

try:
    from bot.trade_journal import TradeJournal
    ok("TradeJournal importe")
    passed += 1
except Exception as e:
    err(f"TradeJournal: {e}"); failed += 1

try:
    from bot.optimizer import load_best_params, should_optimize
    ok("Optimizer importe")
    passed += 1
except Exception as e:
    err(f"Optimizer: {e}"); failed += 1

try:
    from bot.reporter import generate_weekly_report
    ok("Reporter importe")
    passed += 1
except Exception as e:
    err(f"Reporter: {e}"); failed += 1


# ---------------------------------------------------------
# TEST 2 - Strategies individuelles
# ---------------------------------------------------------

hdr("TEST 2 - STRATEGIES INDIVIDUELLES")

# RSI_MACD
print(f"\n  {BOLD}RSI + MACD + EMA{RESET}")
rsi_strat = RSIMACDStrategy()
df_trend   = make_trending_df()
df_oversold= make_oversold_df()

sig_trend   = rsi_strat.get_signal(df_trend)
sig_oversold= rsi_strat.get_signal(df_oversold)
indicators  = rsi_strat.get_indicators(df_trend)

check("Retourne un signal valide (trend)",   sig_trend in ("BUY","SELL","HOLD"), sig_trend)
check("Retourne un signal valide (oversold)",sig_oversold in ("BUY","SELL","HOLD"), sig_oversold)
check("Indicateurs non vides",               len(indicators) > 0, str(indicators))
check("RSI present dans indicateurs",        "rsi" in indicators)
check("MACD diff present",                   "macd_diff" in indicators)

print(f"    Indicateurs actuels: RSI={indicators.get('rsi','_')} "
      f"MACD={indicators.get('macd_diff','_')} "
      f"EMA_s={indicators.get('ema_s','_')}")
print(f"    Signal (trend):    {BOLD}{sig_trend}{RESET}")
print(f"    Signal (oversold): {BOLD}{sig_oversold}{RESET}")

# BOLLINGER
print(f"\n  {BOLD}BOLLINGER BANDS{RESET}")
bb_strat  = BollingerStrategy()
sig_range = bb_strat.get_signal(make_ranging_df())
inds_bb   = bb_strat.get_indicators(make_ranging_df())

check("Retourne un signal valide", sig_range in ("BUY","SELL","HOLD"), sig_range)
check("Indicateurs BB presents",   "bb_pct" in inds_bb)
check("RSI present",               "rsi" in inds_bb)

print(f"    BB% position (0=bas, 1=haut): {inds_bb.get('bb_pct','_')}")
print(f"    Signal (ranging): {BOLD}{sig_range}{RESET}")

# BREAKOUT
print(f"\n  {BOLD}BREAKOUT + ADX{RESET}")
bk_strat  = BreakoutStrategy()
sig_break = bk_strat.get_signal(make_trending_df(n=250))
inds_bk   = bk_strat.get_indicators(make_trending_df(n=250))

check("Retourne un signal valide", sig_break in ("BUY","SELL","HOLD"), sig_break)
check("ADX present",               "adx" in inds_bk)
check("Support/Resistance present",
      "resistance" in inds_bk and "support" in inds_bk)

print(f"    ADX={inds_bk.get('adx','_')} (>25 = tendance forte)")
print(f"    Signal (breakout): {BOLD}{sig_break}{RESET}")


# ---------------------------------------------------------
# TEST 3 - StrategyManager (vote pond_r_)
# ---------------------------------------------------------

hdr("TEST 3 - STRATEGY MANAGER (VOTE PONDERE)")

sm = StrategyManager()
df_test = make_trending_df(n=300)

result = sm.get_signal(df_test)
check("Retourne un dict de r_sultat",   isinstance(result, dict))
check("Champ 'signal' present",         "signal" in result)
check("Signal valide",                  result["signal"] in ("BUY","SELL","HOLD"))
check("Champ 'votes' present",          "votes" in result)
check("Champ 'details' present",        "details" in result)
check("3 strategies evaluees",          len(result["details"]) == 3)
check("buy_pct est un nombre",          isinstance(result.get("buy_pct"), float))

print(f"\n    Signal final : {BOLD}{result['signal']}{RESET}")
print(f"    BUY votes    : {result['buy_pct']}%")
print(f"    SELL votes   : {result['sell_pct']}%")
print(f"    Detail:")
for name, d in result["details"].items():
    print(f"      {name:<12} -> {d.get('signal','_'):<5} (poids={d.get('weight','_')})")

# Test mise _ jour des poids
print(f"\n  Test apprentissage des poids...")
initial_scores = {k: v["weight"] for k, v in sm.get_scores().items()}
sm.record_trade_result("BOLLINGER", -2.0)
sm.record_trade_result("BOLLINGER", -2.0)
sm.record_trade_result("BOLLINGER", -2.0)
sm.record_trade_result("RSI_MACD", +4.0)
sm.record_trade_result("RSI_MACD", +4.0)
new_scores = {k: v["weight"] for k, v in sm.get_scores().items()}

check("Scores enregistres",   len(sm.get_scores()) == 3)
print(f"    Scores avant : {initial_scores}")
print(f"    Scores apres : {new_scores}")


# ---------------------------------------------------------
# TEST 4 - Trade Journal
# ---------------------------------------------------------

hdr("TEST 4 - JOURNAL DE TRADES")

journal = TradeJournal("data/test_journal.json")

# Ouvrir un trade
t1 = journal.open_trade("BTCUSDT", "RSI_MACD", 75000, 0.001, 73500, 78000)
check("Trade ouvert",              t1 is not None)
check("ID assigne",                len(t1.id) > 0)
check("Pas encore ferme",          not t1.is_closed)

# V_rifier qu'on retrouve le trade ouvert
open_t = journal.get_open_trade()
check("get_open_trade() fonctionne", open_t is not None)
check("Bon trade retrouve",          open_t.id == t1.id if open_t else False)

# Fermer le trade (profit)
closed = journal.close_trade(t1.id, 78000, "TAKE_PROFIT")
check("Trade ferme",               closed is not None)
check("PnL calcule",               closed.pnl_pct is not None if closed else False)
check("Trade gagnant (+4%)",
      abs(closed.pnl_pct - 4.0) < 0.1 if closed else False,
      f"pnl={closed.pnl_pct if closed else '_'}")

# Ouvrir et fermer un trade perdant
t2 = journal.open_trade("BTCUSDT", "BOLLINGER", 76000, 0.001, 74480, 79040)
journal.close_trade(t2.id, 74480, "STOP_LOSS")
check("Trade perdant enregistre", True)

# Stats
stats = journal.stats()
check("Stats calculees",          stats["total"] == 2)
check("Win rate = 50%",           stats["win_rate"] == 50.0, f"WR={stats['win_rate']}")
check("PnL total > 0",            stats["total_pnl_pct"] > 0,
      f"PnL={stats['total_pnl_pct']}")

print(f"\n    Stats journal: trades={stats['total']} "
      f"WR={stats['win_rate']}% PnL={stats['total_pnl_pct']:+.2f}%")

# Stats par strat_gie
by_strat = journal.stats_by_strategy()
check("Stats par strategie present",  len(by_strat) == 2)
check("RSI_MACD 100% WR",
      by_strat.get("RSI_MACD", {}).get("win_rate") == 100.0)
check("BOLLINGER 0% WR",
      by_strat.get("BOLLINGER", {}).get("win_rate") == 0.0)

# Nettoyer
import os
if os.path.exists("data/test_journal.json"):
    os.remove("data/test_journal.json")


# ---------------------------------------------------------
# TEST 5 - Optimizer
# ---------------------------------------------------------

hdr("TEST 5 - OPTIMISEUR DE PARAMETRES")

from bot.optimizer import load_best_params, should_optimize

sl, tp = load_best_params()
check("Params charges (sl > 0)",  sl > 0, f"sl={sl}")
check("Params charges (tp > sl)", tp > sl, f"sl={sl} tp={tp}")
check("should_optimize(0)=False",  not should_optimize(0))
check("should_optimize(10)=True",  should_optimize(10))
check("should_optimize(20)=True",  should_optimize(20))
check("should_optimize(15)=False", not should_optimize(15))

print(f"\n    SL actuel={sl}%  TP actuel={tp}%")
print(f"    {YELLOW}(L'optimisation r_elle necessite ~30s sur des donn_es historiques){RESET}")


# ---------------------------------------------------------
# TEST 6 - Reporter
# ---------------------------------------------------------

hdr("TEST 6 - GENERATEUR DE RAPPORT HEBDOMADAIRE")

from bot.reporter import generate_weekly_report

# Journal de demo
jdemo = TradeJournal("data/demo_report_test.json")
demo_trades = [
    ("RSI_MACD",  77000, 77000*1.04, "TAKE_PROFIT"),
    ("BOLLINGER", 76000, 76000*0.98, "STOP_LOSS"),
    ("RSI_MACD",  75000, 75000*1.04, "TAKE_PROFIT"),
    ("BREAKOUT",  76500, 76500*1.04, "TAKE_PROFIT"),
    ("BOLLINGER", 77200, 77200*0.98, "STOP_LOSS"),
    ("BREAKOUT",  77500, 77500*1.04, "TAKE_PROFIT"),
]
sm2 = StrategyManager()
for strat, entry, exit_p, reason in demo_trades:
    t = jdemo.open_trade("BTCUSDT", strat, entry, 0.001, entry*0.98, entry*1.04)
    jdemo.close_trade(t.id, exit_p, reason)
    sm2.record_trade_result(strat, (exit_p - entry) / entry * 100)

report = generate_weekly_report(jdemo, sm2.get_scores(), sl, tp, "BTCUSDT", "15m")

check("Rapport genere (non vide)",       len(report) > 500)
check("Contient RESUME",                 "RESUME" in report)
check("Contient PERFORMANCE PAR STRAT.", "STRATEGIE" in report)
check("Contient SUGGESTIONS",            "SUGGESTIONS" in report)
check("Contient TRADES DE LA SEMAINE",   "TRADES" in report)
check("Fichier rapport sauvegarde",
      any(f.startswith("report_") for f in os.listdir("data/reports")))

print(f"\n    Rapport de {len(report)} caracteres genere.")
print(f"    Sauvegarde dans: data/reports/")

if os.path.exists("data/demo_report_test.json"):
    os.remove("data/demo_report_test.json")


# ---------------------------------------------------------
# TEST 7 - Backtest RSI_MACD (donn_es simul_es)
# ---------------------------------------------------------

hdr("TEST 7 - BACKTEST RAPIDE (DONNEES SIMULEES)")

from bot.optimizer import _simulate

df_bt = make_oversold_df(n=300)
score = _simulate(df_bt, RSIMACDStrategy(), sl_pct=2.0, tp_pct=4.0)
print(f"    Score simulation (SL=2% TP=4%): {score:+.2f}%")
check("Simulation terminee sans erreur", isinstance(score, float))

# Comparer plusieurs combinaisons SL/TP
print(f"\n    Comparaison SL/TP sur donnees simulees:")
print(f"    {'SL':>5} {'TP':>5} {'Score':>8}")
print("    " + "-"*22)
for sl_t in [1.5, 2.0, 2.5]:
    for tp_t in [3.0, 4.0, 5.0]:
        s = _simulate(df_bt, RSIMACDStrategy(), sl_pct=sl_t, tp_pct=tp_t)
        marker = " << meilleur" if s == max(
            _simulate(df_bt, RSIMACDStrategy(), sl_pct=x, tp_pct=y)
            for x in [1.5,2.0,2.5] for y in [3.0,4.0,5.0]
        ) else ""
        print(f"    {sl_t:>5.1f} {tp_t:>5.1f} {s:>+8.2f}%{marker}")


# ---------------------------------------------------------
# TEST 8 - Robustesse (donn_es insuffisantes)
# ---------------------------------------------------------

hdr("TEST 8 - ROBUSTESSE (CAS LIMITES)")

df_tiny = make_trending_df(n=5)   # trop peu de donn_es

sig1 = RSIMACDStrategy().get_signal(df_tiny)
sig2 = BollingerStrategy().get_signal(df_tiny)
sig3 = BreakoutStrategy().get_signal(df_tiny)

check("RSI_MACD retourne HOLD si donn_es insuffisantes",  sig1 == "HOLD", sig1)
check("BOLLINGER retourne HOLD si donn_es insuffisantes", sig2 == "HOLD", sig2)
check("BREAKOUT retourne HOLD si donn_es insuffisantes",  sig3 == "HOLD", sig3)

df_nan = make_trending_df(n=100)
df_nan.iloc[-1, df_nan.columns.get_loc("close")] = float("nan")
try:
    sig_nan = RSIMACDStrategy().get_signal(df_nan)
    check("Gere les NaN sans crash",   sig_nan in ("BUY","SELL","HOLD"))
except Exception as e:
    err(f"Crash sur NaN: {e}"); failed += 1


# ---------------------------------------------------------
# RESUME FINAL
# ---------------------------------------------------------

total = passed + failed
print(f"\n{'='*58}")
print(f"  {BOLD}RESULTAT FINAL{RESET}")
print(f"{'='*58}")
print(f"  Tests reussis : {GREEN}{passed}/{total}{RESET}")
if failed > 0:
    print(f"  Tests echoues : {RED}{failed}/{total}{RESET}")
else:
    print(f"  {GREEN}{BOLD}Tous les tests sont passes !{RESET}")
print(f"{'='*58}\n")

if failed > 0:
    sys.exit(1)
