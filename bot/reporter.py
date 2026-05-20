"""
Weekly report generator — produces a .txt report with stats + suggestions.
Saved in data/reports/report_YYYY-MM-DD.txt
"""
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import List

from bot.trade_journal import TradeJournal, TradeRecord

REPORTS_DIR = os.path.join("data", "reports")
logger = logging.getLogger("trading_bot.reporter")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _week_ago() -> str:
    return (_now_utc() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")


def _divider(char="=", width=58) -> str:
    return char * width


def _section(title: str) -> str:
    return f"\n{_divider()}\n  {title}\n{_divider()}"


# ------------------------------------------------------------------
# Suggestions engine
# ------------------------------------------------------------------

def _generate_suggestions(stats: dict, strategy_stats: dict,
                           scores: dict, sl: float, tp: float) -> List[str]:
    suggestions = []

    if stats["total"] == 0:
        suggestions.append("Aucun trade cette semaine — le marche etait calme ou les seuils sont trop stricts.")
        suggestions.append("Essaie un intervalle plus court (ex: --interval 5m) pour plus de signaux.")
        return suggestions

    wr = stats["win_rate"]
    avg = stats["avg_pnl_pct"]

    # Win rate
    if wr >= 60:
        suggestions.append(f"Win rate excellent ({wr}%) — strategie performante, maintien les parametres.")
    elif wr >= 45:
        suggestions.append(f"Win rate correct ({wr}%) — explore l'augmentation du Take-Profit pour ameliorer l'esperance.")
    else:
        suggestions.append(f"Win rate faible ({wr}%) — considerez d'augmenter les filtres de confirmation (volume, ADX).")

    # SL/TP ratio
    ratio = tp / sl
    if ratio < 1.5:
        suggestions.append(f"Ratio TP/SL ({ratio:.1f}x) trop faible — augmente le TP ou reduis le SL.")
    elif ratio >= 2.5:
        suggestions.append(f"Bon ratio risque/recompense ({ratio:.1f}x) — continue ainsi.")

    # Stop-loss hits
    if stats.get("worst_pct", 0) <= -sl * 0.95:
        suggestions.append("Plusieurs stop-loss touches — le marche est volatile. Essaie SL=1.5% pour limiter les pertes.")

    # TP hits
    if stats.get("best_pct", 0) >= tp * 0.95:
        suggestions.append(f"Take-profit atteint sur certains trades — TP actuel ({tp}%) semble adequat.")

    # Strategy performance
    best_strat = max(strategy_stats.items(),
                     key=lambda x: x[1]["total_pnl_pct"], default=(None, None))
    worst_strat = min(strategy_stats.items(),
                      key=lambda x: x[1]["total_pnl_pct"], default=(None, None))
    if best_strat[0]:
        suggestions.append(f"Meilleure strategie: {best_strat[0]} (+{best_strat[1]['total_pnl_pct']:.2f}%) — conserve-la.")
    if worst_strat[0] and worst_strat[0] != best_strat[0]:
        pnl = worst_strat[1]['total_pnl_pct']
        if pnl < -2:
            suggestions.append(f"Strategie {worst_strat[0]} sous-performe ({pnl:.2f}%) — son poids a ete reduit automatiquement.")

    # Volume
    if avg < 0:
        suggestions.append("PnL moyen negatif — verifie si le volume_ma_period (20) est adapte au marche actuel.")

    return suggestions


# ------------------------------------------------------------------
# Main report builder
# ------------------------------------------------------------------

def generate_weekly_report(journal: TradeJournal, scores: dict,
                            sl: float, tp: float,
                            symbol: str, interval: str) -> str:
    now = _now_utc()
    since = _week_ago()

    weekly_stats = journal.stats(since=since)
    all_stats = journal.stats()
    strategy_stats = journal.stats_by_strategy()
    closed_week = journal.closed_trades(since=since)
    suggestions = _generate_suggestions(weekly_stats, strategy_stats, scores, sl, tp)

    lines = []
    lines.append(_divider())
    lines.append(f"  RAPPORT HEBDOMADAIRE DE TRADING")
    lines.append(f"  Genere le : {now.strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append(f"  Paire     : {symbol}   Intervalle : {interval}")
    lines.append(_divider())

    # --- Weekly summary ---
    lines.append(_section("RESUME DE LA SEMAINE"))
    lines.append(f"  Trades total       : {weekly_stats['total']}")
    lines.append(f"  Gagnants           : {weekly_stats['wins']}")
    lines.append(f"  Perdants           : {weekly_stats['losses']}")
    lines.append(f"  Win rate           : {weekly_stats['win_rate']}%")
    lines.append(f"  PnL moyen/trade    : {weekly_stats['avg_pnl_pct']:+.2f}%")
    lines.append(f"  PnL total semaine  : {weekly_stats['total_pnl_pct']:+.2f}%")
    lines.append(f"  PnL USD semaine    : ${weekly_stats['total_pnl_usd']:+.2f}")
    lines.append(f"  Meilleur trade     : {weekly_stats['best_pct']:+.2f}%")
    lines.append(f"  Pire trade         : {weekly_stats['worst_pct']:+.2f}%")

    # --- All-time summary ---
    lines.append(_section("PERFORMANCE GLOBALE (TOUS LES TRADES)"))
    lines.append(f"  Trades total       : {all_stats['total']}")
    lines.append(f"  Win rate global    : {all_stats['win_rate']}%")
    lines.append(f"  PnL total          : {all_stats['total_pnl_pct']:+.2f}%")
    lines.append(f"  PnL USD total      : ${all_stats['total_pnl_usd']:+.2f}")

    # --- Strategy performance ---
    lines.append(_section("PERFORMANCE PAR STRATEGIE"))
    if strategy_stats:
        for name, s in sorted(strategy_stats.items(),
                               key=lambda x: x[1]["total_pnl_pct"], reverse=True):
            weight = scores.get(name, {}).get("weight", 1.0)
            lines.append(
                f"  {name:<15} trades={s['total']:>3}  WR={s['win_rate']:>5.1f}%"
                f"  avg={s['avg_pnl_pct']:>+6.2f}%  poids={weight:.2f}"
            )
    else:
        lines.append("  Pas encore de donnees par strategie.")

    # --- Trade log this week ---
    lines.append(_section("TRADES DE LA SEMAINE"))
    if closed_week:
        lines.append(f"  {'Date sortie':<22} {'Strategie':<12} {'Entree':>9}"
                     f"  {'Sortie':>9}  {'PnL%':>7}  {'Raison'}")
        lines.append("  " + "-" * 74)
        for t in closed_week:
            lines.append(
                f"  {str(t.exit_time)[:19]:<22} {t.strategy:<12}"
                f" {t.entry_price:>9.2f}  {t.exit_price:>9.2f}"
                f"  {t.pnl_pct:>+6.2f}%  {t.exit_reason}"
            )
    else:
        lines.append("  Aucun trade ferme cette semaine.")

    # --- Current parameters ---
    lines.append(_section("PARAMETRES ACTUELS"))
    lines.append(f"  Stop-Loss          : {sl}%")
    lines.append(f"  Take-Profit        : {tp}%")
    lines.append(f"  Ratio TP/SL        : {tp/sl:.1f}x")

    # --- Suggestions ---
    lines.append(_section("SUGGESTIONS POUR LA SEMAINE PROCHAINE"))
    for i, s in enumerate(suggestions, 1):
        lines.append(f"  {i}. {s}")

    lines.append(f"\n{_divider()}")
    lines.append(f"  Fin du rapport")
    lines.append(_divider())

    report = "\n".join(lines)

    # Save to file
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"report_{now.strftime('%Y-%m-%d')}.txt"
    filepath = os.path.join(REPORTS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info("Rapport hebdomadaire sauvegarde: %s", filepath)
    return report
