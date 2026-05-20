import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.makedirs("data/reports", exist_ok=True)

from bot.strategies.rsi_macd import RSIMACDStrategy
from bot.strategies.bollinger import BollingerStrategy
from bot.strategies.breakout  import BreakoutStrategy
from bot.strategy_manager     import StrategyManager
from bot.trade_journal        import TradeJournal
from bot.optimizer            import load_best_params
from bot.reporter             import generate_weekly_report

print("Modules importes OK")

j = TradeJournal("data/demo_trades.json")
demo = [
    ("RSI_MACD",  77000, 77000*1.04, "TAKE_PROFIT"),
    ("BOLLINGER", 76000, 76000*0.98, "STOP_LOSS"),
    ("RSI_MACD",  75000, 75000*1.04, "TAKE_PROFIT"),
    ("BREAKOUT",  76500, 76500*1.04, "TAKE_PROFIT"),
    ("BOLLINGER", 77200, 77200*0.98, "STOP_LOSS"),
    ("BREAKOUT",  77500, 77500*1.04, "TAKE_PROFIT"),
]
for strat, entry, exit_p, reason in demo:
    t = j.open_trade("BTCUSDT", strat, entry, 0.001,
                     entry*0.98, entry*1.04)
    j.close_trade(t.id, exit_p, reason)

sm = StrategyManager()
for strat, entry, exit_p, _ in demo:
    sm.record_trade_result(strat, (exit_p - entry) / entry * 100)

sl, tp = load_best_params()
report = generate_weekly_report(j, sm.get_scores(), sl, tp, "BTCUSDT", "15m")
print(report)
if os.path.exists("data/demo_trades.json"):
    os.remove("data/demo_trades.json")
