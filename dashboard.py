"""
Dashboard Streamlit pour le Trading Bot Binance.
Lancement : streamlit run dashboard.py
"""
import os
import json
import time
from pathlib import Path

import hmac
import logging
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

logger = logging.getLogger("trading_bot.dashboard")

# --- Setup ---
ROOT = Path(__file__).parent
os.chdir(ROOT)
load_dotenv()

# Injecte les secrets Streamlit Cloud dans os.environ avant d'importer config
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ[_k] = _v
except Exception:
    pass

import importlib
from bot import config
importlib.reload(config)
from bot.trader import Trader
from bot.market_analyzer import MarketAnalyzer
from bot.strategy_manager import StrategyManager
from bot.trade_journal import TradeJournal
from bot.portfolio import Portfolio

st.set_page_config(
    page_title="Trading Bot Dashboard",
    page_icon="📈",
    layout="wide",
)

# --- Authentification ---
def _check_password() -> bool:
    pwd_env = os.getenv("DASHBOARD_PASSWORD", "")
    if not pwd_env:
        return True  # pas de mot de passe configure = acces libre en local
    def _submit():
        entered = st.session_state.get("dashboard_pwd", "")
        st.session_state["authenticated"] = hmac.compare_digest(entered, pwd_env)
    if st.session_state.get("authenticated"):
        return True
    st.text_input("Mot de passe du dashboard", type="password",
                  on_change=_submit, key="dashboard_pwd")
    if st.session_state.get("authenticated") is False:
        st.error("Mot de passe incorrect.")
    st.stop()

_check_password()

st.markdown("""
<style>
[data-testid="metric-container"] { background:#1e1e2e; border-radius:10px; padding:12px; }
.up   { color:#00ff88; font-weight:bold; }
.down { color:#ff4444; font-weight:bold; }
.flat { color:#aaaaaa; }
.section-title { font-size:1.15rem; font-weight:700; margin-bottom:6px; }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------
# Matières premières — symboles Yahoo Finance
# -----------------------------------------------------------------------
COMMODITIES = {
    "🥇 Or":            "GC=F",
    "🥈 Argent":        "SI=F",
    "🛢️ Pétrole (WTI)": "CL=F",
    "🔥 Gaz Naturel":   "NG=F",
    "🔶 Cuivre":        "HG=F",
    "🌾 Blé":           "ZW=F",
}

@st.cache_data(ttl=300)
def get_commodity_data() -> dict:
    result = {}
    for name, sym in COMMODITIES.items():
        try:
            hist = yf.Ticker(sym).history(period="5d")
            if hist.empty:
                continue
            price   = float(hist["Close"].iloc[-1])
            prev    = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
            chg_pct = (price - prev) / prev * 100
            week    = hist["Close"].tolist()
            result[name] = {"price": price, "chg_pct": chg_pct, "week": week, "symbol": sym}
        except Exception:
            pass
    return result

# -----------------------------------------------------------------------
# Helpers Binance
# -----------------------------------------------------------------------

@st.cache_resource
def get_trader(_ts: int = 0):
    load_dotenv(override=True)
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

@st.cache_data(ttl=60)
def get_crypto_market(_trader) -> list:
    """Top 50 cryptos USDT avec prix et variation 24h."""
    try:
        tickers = _trader.client.get_ticker()
        usdt = [
            t for t in tickers
            if t["symbol"].endswith("USDT")
            and not any(x in t["symbol"] for x in ["UP", "DOWN", "BULL", "BEAR"])
            and float(t.get("quoteVolume", 0)) > 5_000_000
        ]
        usdt.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        return usdt[:50]
    except Exception:
        return []

def load_portfolio_file() -> dict:
    path = ROOT / "data" / "portfolio.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}

def load_scores() -> dict:
    path = ROOT / "data" / "strategy_scores.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}

def color_chg(val: float) -> str:
    if val > 0:   return f'<span class="up">▲ {val:+.2f}%</span>'
    if val < 0:   return f'<span class="down">▼ {val:+.2f}%</span>'
    return f'<span class="flat">— {val:.2f}%</span>'

def sparkline(values: list, color: str) -> go.Figure:
    fig = go.Figure(go.Scatter(
        y=values, mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy", fillcolor=color.replace(")", ",0.15)").replace("rgb", "rgba"),
    ))
    fig.update_layout(
        height=60, margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig

# -----------------------------------------------------------------------
# Header
# -----------------------------------------------------------------------

st.title("📈 Trading Bot Dashboard — Multi-Crypto")
st.caption(f"Intervalle : **{config.INTERVAL}** | Max positions : **{config.MAX_POSITIONS}** | Actualisation : **30s**")

if st.sidebar.button("🔄 Reconnecter à Binance"):
    st.cache_resource.clear()

trader       = get_trader(_ts=int(time.time() // 60))
analyzer     = get_analyzer()
strategy_mgr = get_strategy_mgr()
journal      = TradeJournal()

if trader is None or not trader.ping():
    st.error("Impossible de se connecter à Binance. Vérifiez vos clés API (fichier .env en local, ou Secrets dans les paramètres Streamlit Cloud).")
    st.stop()

# -----------------------------------------------------------------------
# Chargement données
# -----------------------------------------------------------------------

with st.spinner("Chargement des données…"):
    _errors = []

    try:
        balance_usdt = trader.get_account_balance("USDT")
    except Exception as exc:
        balance_usdt = 0.0
        _errors.append(f"Solde USDT : {type(exc).__name__}: {exc}")

    try:
        df_klines     = trader.get_klines(limit=200, symbol=config.SYMBOL)
        current_price = float(df_klines["close"].iloc[-1])
    except Exception as exc:
        df_klines     = None
        current_price = 0.0
        _errors.append(f"Klines {config.SYMBOL} : {type(exc).__name__}: {exc}")

    if df_klines is not None:
        try:
            signals = strategy_mgr.get_signal(df_klines)
        except Exception as exc:
            signals = {"signal": "HOLD", "buy_pct": 0, "sell_pct": 0, "details": {}}
            _errors.append(f"Stratégies : {type(exc).__name__}: {exc}")

        try:
            analysis = analyzer.analyze(df_klines)
        except Exception as exc:
            analysis = {"trend": "—", "confidence": 0, "rsi": 0, "ema50": 0,
                        "ema200": 0, "atr_pct": 0, "recommendation": "—", "reasons": []}
            _errors.append(f"Analyse marché : {type(exc).__name__}: {exc}")
    else:
        signals  = {"signal": "HOLD", "buy_pct": 0, "sell_pct": 0, "details": {}}
        analysis = {"trend": "—", "confidence": 0, "rsi": 0, "ema50": 0,
                    "ema200": 0, "atr_pct": 0, "recommendation": "—", "reasons": []}

    try:
        crypto_market = get_crypto_market(trader)
    except Exception as exc:
        crypto_market = []
        _errors.append(f"Marché crypto : {type(exc).__name__}: {exc}")

    try:
        commodities = get_commodity_data()
    except Exception as exc:
        commodities = {}
        _errors.append(f"Matières premières : {type(exc).__name__}: {exc}")

    if _errors:
        with st.expander("⚠️ Erreurs de chargement (cliquer pour voir)", expanded=True):
            for e in _errors:
                st.warning(e)

portfolio_data = load_portfolio_file()
scores  = load_scores()
trades  = journal.closed_trades()
stats   = journal.stats()

# PnL global portefeuille
total_pnl_pct = 0.0
n_pos = len(portfolio_data)
if portfolio_data:
    pnls = []
    for sym, pos in portfolio_data.items():
        try:
            p = trader.get_ticker_price(symbol=sym)
            pnl = (p - pos["entry_price"]) / pos["entry_price"] * 100
            pnls.append(pnl)
        except Exception:
            pass
    total_pnl_pct = sum(pnls) / len(pnls) if pnls else 0.0

# -----------------------------------------------------------------------
# Métriques principales
# -----------------------------------------------------------------------

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Solde USDT",        f"{balance_usdt:,.2f} USDT")
m2.metric(f"{config.SYMBOL}",  f"{current_price:,.2f} USDT")
m3.metric("Positions ouvertes",f"{n_pos} / {config.MAX_POSITIONS}")
m4.metric("PnL portefeuille",  f"{total_pnl_pct:+.2f}%",
          delta_color="normal" if total_pnl_pct >= 0 else "inverse")
m5.metric("Signal consensus",  signals["signal"],
          f"BUY {signals['buy_pct']:.0f}%  SELL {signals['sell_pct']:.0f}%")

st.divider()

# -----------------------------------------------------------------------
# MATIÈRES PREMIÈRES
# -----------------------------------------------------------------------

st.markdown('<p class="section-title">🌍 Matières Premières — Prix en direct</p>', unsafe_allow_html=True)

if commodities:
    cols = st.columns(len(commodities))
    for col, (name, data) in zip(cols, commodities.items()):
        chg   = data["chg_pct"]
        color = "#00ff88" if chg >= 0 else "#ff4444"
        col.markdown(f"**{name}**")
        col.metric(
            label=data["symbol"],
            value=f"{data['price']:,.2f}",
            delta=f"{chg:+.2f}%",
            delta_color="normal" if chg >= 0 else "inverse",
        )
        col.plotly_chart(sparkline(data["week"], color), use_container_width=True)
else:
    st.warning("Données des matières premières indisponibles (vérifiez la connexion internet).")

st.divider()

# -----------------------------------------------------------------------
# Graphique chandelles BTC (ou symbole principal)
# -----------------------------------------------------------------------

st.markdown(f'<p class="section-title">📊 Graphique {config.SYMBOL}</p>', unsafe_allow_html=True)

if df_klines is not None:
    close  = df_klines["close"]
    ema50  = close.ewm(span=50,  adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    fig_chart = go.Figure()
    fig_chart.add_trace(go.Candlestick(
        x=df_klines.index,
        open=df_klines["open"], high=df_klines["high"],
        low=df_klines["low"],   close=df_klines["close"],
        name="Prix",
        increasing_line_color="#00ff88", decreasing_line_color="#ff4444",
    ))
    fig_chart.add_trace(go.Scatter(x=df_klines.index, y=ema50,
        name="EMA 50",  line=dict(color="#f7931a", width=1.5)))
    fig_chart.add_trace(go.Scatter(x=df_klines.index, y=ema200,
        name="EMA 200", line=dict(color="#627eea", width=1.5)))

    for t in trades[-20:]:
        try:
            fig_chart.add_trace(go.Scatter(
                x=[pd.Timestamp(t.entry_time)], y=[t.entry_price],
                mode="markers", marker=dict(symbol="triangle-up", color="#00ff88", size=10),
                showlegend=False,
            ))
            if t.exit_price:
                fig_chart.add_trace(go.Scatter(
                    x=[pd.Timestamp(t.exit_time)], y=[t.exit_price],
                    mode="markers", marker=dict(symbol="triangle-down", color="#ff4444", size=10),
                    showlegend=False,
                ))
        except Exception:
            pass

    fig_chart.update_layout(
        template="plotly_dark", height=420,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
    )
    st.plotly_chart(fig_chart, use_container_width=True)
else:
    st.warning("Graphique indisponible — impossible de charger les données OHLCV.")

# -----------------------------------------------------------------------
# Analyse marché + Signaux stratégies
# -----------------------------------------------------------------------

col_a, col_s = st.columns(2)

with col_a:
    st.markdown('<p class="section-title">🔍 Analyse du marché</p>', unsafe_allow_html=True)
    trend_color = {"BULL": "#00ff88", "BEAR": "#ff4444"}.get(analysis["trend"], "#aaaaaa")
    reco_color  = {"ACHETER": "#00ff88", "EVITER": "#ff4444"}.get(analysis["recommendation"], "#f7931a")
    st.markdown(f"""
| Indicateur | Valeur |
|---|---|
| Tendance | <span style="color:{trend_color};font-weight:bold">{analysis['trend']}</span> |
| Confiance | **{analysis['confidence']:.0f}%** |
| RSI | {analysis['rsi']} |
| EMA 50 | {analysis['ema50']:,.2f} |
| EMA 200 | {analysis['ema200']:,.2f} |
| Volatilité | {analysis['atr_pct']}% |
| **Recommandation** | <span style="color:{reco_color};font-weight:bold">{analysis['recommendation']}</span> |
""", unsafe_allow_html=True)
    with st.expander("Détails de l'analyse"):
        for r in analysis["reasons"]:
            st.markdown(f"• {r}")

with col_s:
    st.markdown('<p class="section-title">🤖 Signaux des 7 stratégies</p>', unsafe_allow_html=True)
    rows_sig = []
    for name, detail in signals["details"].items():
        sig  = detail.get("signal", "HOLD")
        w    = detail.get("weight", 1.0)
        sc   = scores.get(name, {})
        rows_sig.append({
            "Stratégie": name,
            "Signal": sig,
            "Poids": f"{w:.2f}",
            "Win Rate": f"{sc.get('win_rate', 0):.1f}%",
            "Trades": sc.get("trades", 0),
        })
    df_sig = pd.DataFrame(rows_sig)

    def color_sig(val):
        if val == "BUY":  return "color:#00ff88;font-weight:bold"
        if val == "SELL": return "color:#ff4444;font-weight:bold"
        return "color:#aaaaaa"

    st.dataframe(df_sig.style.map(color_sig, subset=["Signal"]),
                 use_container_width=True, hide_index=True)
    st.markdown(f"**BUY {signals['buy_pct']:.0f}%** | **SELL {signals['sell_pct']:.0f}%**")
    st.progress(int(signals["buy_pct"]) / 100)

st.divider()

# -----------------------------------------------------------------------
# PORTEFEUILLE MULTI-CRYPTO — positions ouvertes avec évolution
# -----------------------------------------------------------------------

st.markdown('<p class="section-title">💼 Portefeuille — Positions ouvertes</p>', unsafe_allow_html=True)

if portfolio_data:
    rows_port = []
    for sym, pos in portfolio_data.items():
        try:
            price  = trader.get_ticker_price(symbol=sym)
            pnl_p  = (price - pos["entry_price"]) / pos["entry_price"] * 100
            pnl_u  = (price - pos["entry_price"]) * pos["quantity"]
            sl_dist = (price - pos["stop_loss"]) / price * 100
            tp_dist = (pos["take_profit"] - price) / price * 100
            rows_port.append({
                "Crypto":       sym,
                "Stratégie":    pos.get("strategy", "—"),
                "Entrée":       f"{pos['entry_price']:,.4f}",
                "Prix actuel":  f"{price:,.4f}",
                "PnL %":        f"{pnl_p:+.2f}%",
                "PnL USDT":     f"{pnl_u:+.4f}",
                "Stop Loss":    f"{pos['stop_loss']:,.4f}",
                "Take Profit":  f"{pos['take_profit']:,.4f}",
                "Dist. SL":     f"{sl_dist:.2f}%",
                "Dist. TP":     f"{tp_dist:.2f}%",
            })
        except Exception:
            pass

    df_port = pd.DataFrame(rows_port)

    def color_pnl_port(val):
        if isinstance(val, str) and val.startswith("+"): return "color:#00ff88;font-weight:bold"
        if isinstance(val, str) and val.startswith("-"): return "color:#ff4444;font-weight:bold"
        return ""

    st.dataframe(
        df_port.style.map(color_pnl_port, subset=["PnL %", "PnL USDT"]),
        use_container_width=True, hide_index=True,
    )

    # Mini graphiques des positions
    st.markdown("**Évolution des positions (dernières 24h)**")
    pos_cols = st.columns(min(len(portfolio_data), 4))
    for col, (sym, pos) in zip(pos_cols, list(portfolio_data.items())[:4]):
        try:
            df_pos = trader.get_klines(limit=96, interval="15m", symbol=sym)
            close_pos = df_pos["close"].tolist()
            entry = pos["entry_price"]
            last  = close_pos[-1]
            pnl   = (last - entry) / entry * 100
            clr   = "#00ff88" if pnl >= 0 else "#ff4444"
            col.markdown(f"**{sym}** {'+' if pnl>=0 else ''}{pnl:.2f}%")
            col.plotly_chart(sparkline(close_pos, clr), use_container_width=True)
        except Exception:
            pass
else:
    st.info("Aucune position ouverte — le bot surveille le marché et cherche des opportunités.")

st.divider()

# -----------------------------------------------------------------------
# MARCHÉ CRYPTO — Top 50 par volume avec évolution 24h
# -----------------------------------------------------------------------

st.markdown('<p class="section-title">🪙 Marché Crypto — Top 50 par volume (évolution 24h)</p>', unsafe_allow_html=True)

if crypto_market:
    rows_crypto = []
    for t in crypto_market:
        chg = float(t.get("priceChangePercent", 0))
        rows_crypto.append({
            "Crypto":           t["symbol"],
            "Prix (USDT)":      f"{float(t['lastPrice']):,.4f}",
            "Variation 24h":    f"{chg:+.2f}%",
            "Volume 24h (USDT)": f"{float(t['quoteVolume']):,.0f}",
            "Haut 24h":         f"{float(t['highPrice']):,.4f}",
            "Bas 24h":          f"{float(t['lowPrice']):,.4f}",
            "Trades 24h":       int(t.get("count", 0)),
        })

    df_crypto = pd.DataFrame(rows_crypto)

    def color_variation(val):
        if isinstance(val, str) and val.startswith("+"): return "color:#00ff88"
        if isinstance(val, str) and val.startswith("-"): return "color:#ff4444"
        return ""

    # Filtre rapide
    search = st.text_input("🔍 Rechercher une crypto (ex: ETH, BNB, SOL...)", "")
    if search:
        df_crypto = df_crypto[df_crypto["Crypto"].str.contains(search.upper())]

    st.dataframe(
        df_crypto.style.map(color_variation, subset=["Variation 24h"]),
        use_container_width=True, hide_index=True, height=400,
    )

    # Graphique top 10 hausses vs baisses
    df_chart = pd.DataFrame([{
        "symbol": t["symbol"],
        "chg": float(t.get("priceChangePercent", 0))
    } for t in crypto_market])
    df_chart = df_chart.sort_values("chg", ascending=False)

    top10_up   = df_chart.head(10)
    top10_down = df_chart.tail(10).sort_values("chg")

    c_up, c_down = st.columns(2)
    with c_up:
        st.markdown("**🟢 Top 10 hausses**")
        fig_up = px.bar(top10_up, x="symbol", y="chg",
                        color_discrete_sequence=["#00ff88"],
                        labels={"chg": "Variation %", "symbol": ""})
        fig_up.update_layout(template="plotly_dark", height=250,
                             margin=dict(l=0,r=0,t=10,b=0))
        st.plotly_chart(fig_up, use_container_width=True)

    with c_down:
        st.markdown("**🔴 Top 10 baisses**")
        fig_down = px.bar(top10_down, x="symbol", y="chg",
                          color_discrete_sequence=["#ff4444"],
                          labels={"chg": "Variation %", "symbol": ""})
        fig_down.update_layout(template="plotly_dark", height=250,
                               margin=dict(l=0,r=0,t=10,b=0))
        st.plotly_chart(fig_down, use_container_width=True)

st.divider()

# -----------------------------------------------------------------------
# Statistiques + Historique
# -----------------------------------------------------------------------

st.markdown('<p class="section-title">📈 Statistiques de trading</p>', unsafe_allow_html=True)
s1, s2, s3, s4, s5 = st.columns(5)
s1.metric("Total trades",  stats.get("total", 0))
s2.metric("Gagnants",      stats.get("wins", 0))
s3.metric("Perdants",      stats.get("losses", 0))
s4.metric("Win rate",      f"{stats.get('win_rate', 0):.1f}%")
s5.metric("PnL total",     f"{stats.get('total_pnl_usd', 0):+.2f} USDT")

st.divider()
st.markdown('<p class="section-title">📋 Historique des trades</p>', unsafe_allow_html=True)

if trades:
    rows_hist = []
    for t in reversed(trades[-30:]):
        rows_hist.append({
            "Date entrée":  t.entry_time,
            "Date sortie":  t.exit_time or "—",
            "Crypto":       t.symbol,
            "Stratégie":    t.strategy,
            "Entrée":       f"{t.entry_price:,.4f}",
            "Sortie":       f"{t.exit_price:,.4f}" if t.exit_price else "—",
            "Raison":       t.exit_reason or "—",
            "PnL %":        f"{t.pnl_pct:+.2f}%" if t.pnl_pct is not None else "—",
            "PnL USDT":     f"{t.pnl_usd:+.4f}" if t.pnl_usd is not None else "—",
        })
    df_hist = pd.DataFrame(rows_hist)

    def color_h(val):
        if isinstance(val, str) and val.startswith("+"): return "color:#00ff88"
        if isinstance(val, str) and val.startswith("-"): return "color:#ff4444"
        return ""

    st.dataframe(df_hist.style.map(color_h, subset=["PnL %", "PnL USDT"]),
                 use_container_width=True, hide_index=True)
else:
    st.info("Aucun trade clôturé pour l'instant.")

# -----------------------------------------------------------------------
# Auto-refresh 30s
# -----------------------------------------------------------------------

st.divider()
st.caption(f"Mise à jour : {pd.Timestamp.now().strftime('%H:%M:%S')} — Prochaine dans 30s")
time.sleep(30)
st.rerun()
