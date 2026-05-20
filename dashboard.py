"""
Dashboard Streamlit pour le Trading Bot Binance.
Lancement : streamlit run dashboard.py
"""
import os
import json
import time
from pathlib import Path

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from dotenv import load_dotenv

# --- Setup ---
ROOT = Path(__file__).parent
os.chdir(ROOT)
load_dotenv()

from bot import config
from bot.trader import Trader
from bot.market_analyzer import MarketAnalyzer
from bot.strategy_manager import StrategyManager
from bot.trade_journal import TradeJournal

st.set_page_config(
    page_title="Trading Bot Dashboard",
    page_icon="📈",
    layout="wide",
)

# --- CSS ---
st.markdown("""
<style>
[data-testid="metric-container"] { background:#1e1e2e; border-radius:10px; padding:12px; }
.buy-signal  { color:#00ff88; font-weight:bold; }
.sell-signal { color:#ff4444; font-weight:bold; }
.hold-signal { color:#aaaaaa; }
.section-title { font-size:1.1rem; font-weight:600; margin-bottom:8px; }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

@st.cache_resource
def get_trader():
    try:
        return Trader(testnet=False)
    except Exception:
        return None


@st.cache_resource
def get_analyzer():
    return MarketAnalyzer()


@st.cache_resource
def get_strategy_mgr():
    return StrategyManager()


def load_position() -> dict | None:
    path = ROOT / "positions.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data
        except Exception:
            pass
    return None


def load_scores() -> dict:
    path = ROOT / "data" / "strategy_scores.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def signal_badge(sig: str) -> str:
    css = {"BUY": "buy-signal", "SELL": "sell-signal"}.get(sig, "hold-signal")
    return f'<span class="{css}">{sig}</span>'


# -----------------------------------------------------------------------
# Page header
# -----------------------------------------------------------------------

st.title("📈 Trading Bot Dashboard")
st.caption(f"Symbole : **{config.SYMBOL}** | Intervalle : **{config.INTERVAL}** | Actualisation auto toutes les 30s")

trader = get_trader()
analyzer = get_analyzer()
strategy_mgr = get_strategy_mgr()
journal = TradeJournal()

if trader is None or not trader.ping():
    st.error("Impossible de se connecter à Binance. Vérifiez vos clés API dans le fichier .env")
    st.stop()

# -----------------------------------------------------------------------
# Données en direct
# -----------------------------------------------------------------------

with st.spinner("Chargement des données…"):
    try:
        current_price = trader.get_ticker_price()
        balance_usdt  = trader.get_account_balance("USDT")
        df_klines     = trader.get_klines(limit=200)
        signals       = strategy_mgr.get_signal(df_klines)
        analysis      = analyzer.analyze(df_klines)
    except Exception as exc:
        st.error(f"Erreur lors du chargement : {exc}")
        st.stop()

position  = load_position()
scores    = load_scores()
trades    = journal.closed_trades()
stats     = journal.stats()
open_trade = journal.get_open_trade()

# -----------------------------------------------------------------------
# Métriques principales
# -----------------------------------------------------------------------

pnl_pct = 0.0
if position and open_trade:
    pnl_pct = round((current_price - position["entry_price"]) / position["entry_price"] * 100, 2)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Prix actuel", f"{current_price:,.2f} USDT")
col2.metric("Solde USDT", f"{balance_usdt:,.2f} USDT")
col3.metric(
    "Position",
    f"{position['quantity']:.5f} BTC" if position else "Aucune",
    f"Entrée @ {position['entry_price']:,.2f}" if position else None,
)
col4.metric(
    "PnL non réalisé",
    f"{pnl_pct:+.2f}%" if position else "—",
    delta_color="normal" if pnl_pct >= 0 else "inverse",
)
col5.metric(
    "Signal consensus",
    signals["signal"],
    f"BUY {signals['buy_pct']:.0f}%  SELL {signals['sell_pct']:.0f}%",
)

st.divider()

# -----------------------------------------------------------------------
# Graphique chandelles
# -----------------------------------------------------------------------

st.markdown('<p class="section-title">Graphique des prix</p>', unsafe_allow_html=True)

close = df_klines["close"]
ema50  = close.ewm(span=50,  adjust=False).mean()
ema200 = close.ewm(span=200, adjust=False).mean()

fig = go.Figure()

fig.add_trace(go.Candlestick(
    x=df_klines.index,
    open=df_klines["open"],
    high=df_klines["high"],
    low=df_klines["low"],
    close=df_klines["close"],
    name="Prix",
    increasing_line_color="#00ff88",
    decreasing_line_color="#ff4444",
))

fig.add_trace(go.Scatter(
    x=df_klines.index, y=ema50,
    name="EMA 50", line=dict(color="#f7931a", width=1.5),
))
fig.add_trace(go.Scatter(
    x=df_klines.index, y=ema200,
    name="EMA 200", line=dict(color="#627eea", width=1.5),
))

# Lignes SL / TP si position ouverte
if position:
    fig.add_hline(
        y=position["stop_loss"], line_color="#ff4444", line_dash="dash",
        annotation_text=f"SL {position['stop_loss']:,.2f}", annotation_position="left",
    )
    fig.add_hline(
        y=position["take_profit"], line_color="#00ff88", line_dash="dash",
        annotation_text=f"TP {position['take_profit']:,.2f}", annotation_position="left",
    )
    fig.add_hline(
        y=position["entry_price"], line_color="#ffffff", line_dash="dot",
        annotation_text=f"Entrée {position['entry_price']:,.2f}", annotation_position="left",
    )

# Points d'achat/vente sur le graphique (derniers 20 trades)
for t in trades[-20:]:
    try:
        fig.add_trace(go.Scatter(
            x=[pd.Timestamp(t.entry_time)], y=[t.entry_price],
            mode="markers", marker=dict(symbol="triangle-up", color="#00ff88", size=10),
            name="Achat", showlegend=False,
        ))
        if t.exit_price:
            fig.add_trace(go.Scatter(
                x=[pd.Timestamp(t.exit_time)], y=[t.exit_price],
                mode="markers", marker=dict(symbol="triangle-down", color="#ff4444", size=10),
                name="Vente", showlegend=False,
            ))
    except Exception:
        pass

fig.update_layout(
    template="plotly_dark",
    height=450,
    xaxis_rangeslider_visible=False,
    margin=dict(l=10, r=10, t=10, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
)
st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------------
# Analyse marché + Signaux stratégies
# -----------------------------------------------------------------------

col_analysis, col_signals = st.columns(2)

with col_analysis:
    st.markdown('<p class="section-title">🔍 Analyse du marché</p>', unsafe_allow_html=True)

    trend_color = {"BULL": "#00ff88", "BEAR": "#ff4444"}.get(analysis["trend"], "#aaaaaa")
    reco_color  = {"ACHETER": "#00ff88", "EVITER": "#ff4444"}.get(analysis["recommendation"], "#f7931a")

    st.markdown(f"""
| Indicateur | Valeur |
|---|---|
| Tendance | <span style="color:{trend_color}; font-weight:bold">{analysis['trend']}</span> |
| Confiance | **{analysis['confidence']:.0f}%** |
| RSI | {analysis['rsi']} |
| EMA 50 | {analysis['ema50']:,.2f} |
| EMA 200 | {analysis['ema200']:,.2f} |
| Volatilité | {analysis['atr_pct']}% |
| **Recommandation** | <span style="color:{reco_color}; font-weight:bold">{analysis['recommendation']}</span> |
""", unsafe_allow_html=True)

    with st.expander("Détails de l'analyse"):
        for r in analysis["reasons"]:
            st.markdown(f"• {r}")

with col_signals:
    st.markdown('<p class="section-title">📊 Signaux des stratégies</p>', unsafe_allow_html=True)

    rows = []
    for name, detail in signals["details"].items():
        sig   = detail.get("signal", "HOLD")
        weight = detail.get("weight", 1.0)
        score_data = scores.get(name, {})
        rows.append({
            "Stratégie": name,
            "Signal": sig,
            "Poids": f"{weight:.2f}",
            "Win Rate": f"{score_data.get('win_rate', 0):.1f}%",
            "Trades": score_data.get("trades", 0),
        })

    df_sig = pd.DataFrame(rows)

    def color_signal(val):
        if val == "BUY":
            return "color: #00ff88; font-weight: bold"
        elif val == "SELL":
            return "color: #ff4444; font-weight: bold"
        return "color: #aaaaaa"

    st.dataframe(
        df_sig.style.map(color_signal, subset=["Signal"]),
        use_container_width=True,
        hide_index=True,
    )

    # Barre de consensus
    st.markdown(f"**Consensus BUY :** {signals['buy_pct']:.0f}%  |  **SELL :** {signals['sell_pct']:.0f}%")
    st.progress(int(signals["buy_pct"]) / 100)

# -----------------------------------------------------------------------
# Position ouverte
# -----------------------------------------------------------------------

st.divider()
st.markdown('<p class="section-title">📌 Position en cours</p>', unsafe_allow_html=True)

if position and open_trade:
    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("Stratégie", open_trade.strategy)
    p2.metric("Prix d'entrée", f"{position['entry_price']:,.2f}")
    p3.metric("Stop Loss", f"{position['stop_loss']:,.2f}")
    p4.metric("Take Profit", f"{position['take_profit']:,.2f}")
    p5.metric("PnL", f"{pnl_pct:+.2f}%", delta_color="normal" if pnl_pct >= 0 else "inverse")
else:
    st.info("Aucune position ouverte en ce moment. Le bot surveille le marché.")

# -----------------------------------------------------------------------
# Statistiques globales
# -----------------------------------------------------------------------

st.divider()
st.markdown('<p class="section-title">📈 Statistiques de trading</p>', unsafe_allow_html=True)

s1, s2, s3, s4, s5 = st.columns(5)
s1.metric("Total trades", stats.get("total", 0))
s2.metric("Gagnants", stats.get("wins", 0))
s3.metric("Perdants", stats.get("losses", 0))
s4.metric("Win rate", f"{stats.get('win_rate', 0):.1f}%")
s5.metric("PnL total", f"{stats.get('total_pnl_usd', 0):+.2f} USDT")

# -----------------------------------------------------------------------
# Historique des trades
# -----------------------------------------------------------------------

st.divider()
st.markdown('<p class="section-title">📋 Historique des trades</p>', unsafe_allow_html=True)

if trades:
    rows = []
    for t in reversed(trades[-20:]):
        pnl_pct_val = t.pnl_pct or 0
        rows.append({
            "Date entrée":  t.entry_time,
            "Date sortie":  t.exit_time or "—",
            "Stratégie":    t.strategy,
            "Entrée":       f"{t.entry_price:,.2f}",
            "Sortie":       f"{t.exit_price:,.2f}" if t.exit_price else "—",
            "Raison":       t.exit_reason or "—",
            "PnL %":        f"{pnl_pct_val:+.2f}%",
            "PnL USDT":     f"{t.pnl_usd:+.2f}" if t.pnl_usd is not None else "—",
        })

    df_trades = pd.DataFrame(rows)

    def color_pnl(val):
        if isinstance(val, str) and val.startswith("+"):
            return "color: #00ff88"
        elif isinstance(val, str) and val.startswith("-"):
            return "color: #ff4444"
        return ""

    st.dataframe(
        df_trades.style.map(color_pnl, subset=["PnL %", "PnL USDT"]),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("Aucun trade clôturé pour l'instant.")

# -----------------------------------------------------------------------
# Auto-refresh toutes les 30 secondes
# -----------------------------------------------------------------------

st.divider()
st.caption(f"Dernière mise à jour : {pd.Timestamp.now().strftime('%H:%M:%S')}  —  Prochaine dans 30s")
time.sleep(30)
st.rerun()
