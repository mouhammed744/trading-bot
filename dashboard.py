"""
Dashboard Streamlit pour le Trading Bot Binance.
Lancement : streamlit run dashboard.py
"""
import os
import json
import time
import importlib
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
        return True
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
# Matières premières
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
# Helpers Binance + fallbacks
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
    """Top 50 cryptos — Binance en priorité, CoinGecko en fallback."""
    if _trader is not None:
        try:
            tickers = _trader.client.get_ticker()
            usdt = [
                t for t in tickers
                if t["symbol"].endswith("USDT")
                and not any(x in t["symbol"] for x in ["UP", "DOWN", "BULL", "BEAR"])
                and float(t.get("quoteVolume", 0)) > 5_000_000
            ]
            usdt.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
            if usdt:
                return usdt[:50]
        except Exception:
            pass
    # Fallback CoinGecko (API publique, aucune auth requise)
    try:
        import requests as _req
        r = _req.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "order": "market_cap_desc",
                    "per_page": 50, "page": 1},
            timeout=10,
        )
        coins = r.json()
        result = []
        for c in coins:
            try:
                result.append({
                    "symbol":             c["symbol"].upper() + "USDT",
                    "lastPrice":          str(c.get("current_price") or 0),
                    "priceChangePercent": str(round(c.get("price_change_percentage_24h") or 0, 2)),
                    "quoteVolume":        str(c.get("total_volume") or 0),
                    "highPrice":          str(c.get("high_24h") or 0),
                    "lowPrice":           str(c.get("low_24h") or 0),
                    "count":              0,
                })
            except Exception:
                pass
        return result
    except Exception:
        return []

@st.cache_data(ttl=300)
def get_btc_ohlcv_fallback():
    """Données OHLCV BTC via yfinance si Binance indisponible."""
    try:
        hist = yf.Ticker("BTC-USD").history(period="7d", interval="1h")
        if hist.empty:
            return None
        df = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        return df
    except Exception:
        return None

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

binance_ok = trader is not None and trader.ping()
if not binance_ok:
    st.warning("⚠️ Binance inaccessible depuis ce serveur (restriction réseau). Solde indisponible — données de marché via sources alternatives.")

# -----------------------------------------------------------------------
# Chargement données
# -----------------------------------------------------------------------

with st.spinner("Chargement des données…"):
    balance_usdt = None
    if binance_ok:
        try:
            balance_usdt = trader.get_account_balance("USDT")
        except Exception:
            pass

    df_klines     = None
    current_price = 0.0
    if binance_ok:
        try:
            df_klines     = trader.get_klines(limit=200, symbol=config.SYMBOL)
            current_price = float(df_klines["close"].iloc[-1])
        except Exception:
            pass
    if df_klines is None:
        df_klines = get_btc_ohlcv_fallback()
        if df_klines is not None:
            current_price = float(df_klines["close"].iloc[-1])

    if df_klines is not None:
        try:
            signals = strategy_mgr.get_signal(df_klines)
        except Exception:
            signals = {"signal": "HOLD", "buy_pct": 0, "sell_pct": 0, "details": {}}
        try:
            analysis = analyzer.analyze(df_klines)
        except Exception:
            analysis = {"trend": "—", "confidence": 0, "rsi": 0, "ema50": 0,
                        "ema200": 0, "atr_pct": 0, "recommendation": "—", "reasons": []}
    else:
        signals  = {"signal": "—", "buy_pct": 0, "sell_pct": 0, "details": {}}
        analysis = {"trend": "—", "confidence": 0, "rsi": 0, "ema50": 0,
                    "ema200": 0, "atr_pct": 0, "recommendation": "—", "reasons": []}

    crypto_market = get_crypto_market(trader if binance_ok else None)
    commodities   = get_commodity_data()

portfolio_data = load_portfolio_file()
scores  = load_scores()
trades  = journal.closed_trades()
stats   = journal.stats()

total_pnl_pct = 0.0
n_pos = len(portfolio_data)
if portfolio_data and binance_ok:
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
m1.metric("Solde USDT",         f"{balance_usdt:,.2f} USDT" if balance_usdt is not None else "N/A")
m2.metric(f"{config.SYMBOL}",   f"{current_price:,.2f} USDT" if current_price else "N/A")
m3.metric("Positions ouvertes", f"{n_pos} / {config.MAX_POSITIONS}")
m4.metric("PnL portefeuille",   f"{total_pnl_pct:+.2f}%" if binance_ok else "N/A",
          delta_color="normal" if total_pnl_pct >= 0 else "inverse")
m5.metric("Signal consensus",   signals["signal"],
          f"BUY {signals['buy_pct']:.0f}%  SELL {signals['sell_pct']:.0f}%" if signals["signal"] not in ("—", "HOLD") else "")

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
    st.warning("Données des matières premières indisponibles.")

st.divider()

# -----------------------------------------------------------------------
# Graphique chandelles
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
    st.warning("Graphique indisponible.")

# -----------------------------------------------------------------------
# Analyse marché + Signaux
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
        sig = detail.get("signal", "HOLD")
        w   = detail.get("weight", 1.0)
        sc  = scores.get(name, {})
        rows_sig.append({
            "Stratégie": name,
            "Signal":    sig,
            "Poids":     f"{w:.2f}",
            "Win Rate":  f"{sc.get('win_rate', 0):.1f}%",
            "Trades":    sc.get("trades", 0),
        })
    df_sig = pd.DataFrame(rows_sig)

    def color_sig(val):
        if val == "BUY":  return "color:#00ff88;font-weight:bold"
        if val == "SELL": return "color:#ff4444;font-weight:bold"
        return "color:#aaaaaa"

    if not df_sig.empty:
        st.dataframe(df_sig.style.map(color_sig, subset=["Signal"]),
                     use_container_width=True, hide_index=True)
        st.markdown(f"**BUY {signals['buy_pct']:.0f}%** | **SELL {signals['sell_pct']:.0f}%**")
        st.progress(int(signals["buy_pct"]) / 100)
    else:
        st.info("Signaux indisponibles.")

st.divider()

# -----------------------------------------------------------------------
# PORTEFEUILLE
# -----------------------------------------------------------------------

st.markdown('<p class="section-title">💼 Portefeuille — Positions ouvertes</p>', unsafe_allow_html=True)

if portfolio_data and binance_ok:
    rows_port = []
    for sym, pos in portfolio_data.items():
        try:
            price   = trader.get_ticker_price(symbol=sym)
            pnl_p   = (price - pos["entry_price"]) / pos["entry_price"] * 100
            pnl_u   = (price - pos["entry_price"]) * pos["quantity"]
            sl_dist = (price - pos["stop_loss"]) / price * 100
            tp_dist = (pos["take_profit"] - price) / price * 100
            rows_port.append({
                "Crypto":      sym,
                "Stratégie":   pos.get("strategy", "—"),
                "Entrée":      f"{pos['entry_price']:,.4f}",
                "Prix actuel": f"{price:,.4f}",
                "PnL %":       f"{pnl_p:+.2f}%",
                "PnL USDT":    f"{pnl_u:+.4f}",
                "Stop Loss":   f"{pos['stop_loss']:,.4f}",
                "Take Profit": f"{pos['take_profit']:,.4f}",
                "Dist. SL":    f"{sl_dist:.2f}%",
                "Dist. TP":    f"{tp_dist:.2f}%",
            })
        except Exception:
            pass
    if rows_port:
        df_port = pd.DataFrame(rows_port)
        def color_pnl_port(val):
            if isinstance(val, str) and val.startswith("+"): return "color:#00ff88;font-weight:bold"
            if isinstance(val, str) and val.startswith("-"): return "color:#ff4444;font-weight:bold"
            return ""
        st.dataframe(df_port.style.map(color_pnl_port, subset=["PnL %", "PnL USDT"]),
                     use_container_width=True, hide_index=True)
else:
    st.info("Aucune position ouverte — le bot surveille le marché.")

st.divider()

# -----------------------------------------------------------------------
# MARCHÉ CRYPTO — Top 50
# -----------------------------------------------------------------------

st.markdown('<p class="section-title">🪙 Marché Crypto — Top 50 (évolution 24h)</p>', unsafe_allow_html=True)

if crypto_market:
    rows_crypto = []
    for t in crypto_market:
        try:
            chg = float(t.get("priceChangePercent", 0))
            rows_crypto.append({
                "Crypto":            t["symbol"],
                "Prix (USDT)":       f"{float(t['lastPrice']):,.4f}",
                "Variation 24h":     f"{chg:+.2f}%",
                "Volume 24h (USDT)": f"{float(t['quoteVolume']):,.0f}",
                "Haut 24h":          f"{float(t['highPrice']):,.4f}",
                "Bas 24h":           f"{float(t['lowPrice']):,.4f}",
            })
        except Exception:
            pass

    if rows_crypto:
        df_crypto = pd.DataFrame(rows_crypto)

        def color_variation(val):
            if isinstance(val, str) and val.startswith("+"): return "color:#00ff88"
            if isinstance(val, str) and val.startswith("-"): return "color:#ff4444"
            return ""

        search = st.text_input("🔍 Rechercher une crypto (ex: ETH, BNB, SOL...)", "")
        if search:
            df_crypto = df_crypto[df_crypto["Crypto"].str.contains(search.upper())]

        st.dataframe(df_crypto.style.map(color_variation, subset=["Variation 24h"]),
                     use_container_width=True, hide_index=True, height=400)

        df_chg = pd.DataFrame([{
            "symbol": t["symbol"],
            "chg":    float(t.get("priceChangePercent", 0))
        } for t in crypto_market]).sort_values("chg", ascending=False)

        c_up, c_down = st.columns(2)
        with c_up:
            st.markdown("**🟢 Top 10 hausses**")
            fig_up = px.bar(df_chg.head(10), x="symbol", y="chg",
                            color_discrete_sequence=["#00ff88"],
                            labels={"chg": "Variation %", "symbol": ""})
            fig_up.update_layout(template="plotly_dark", height=250,
                                 margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_up, use_container_width=True)
        with c_down:
            st.markdown("**🔴 Top 10 baisses**")
            fig_down = px.bar(df_chg.tail(10).sort_values("chg"), x="symbol", y="chg",
                              color_discrete_sequence=["#ff4444"],
                              labels={"chg": "Variation %", "symbol": ""})
            fig_down.update_layout(template="plotly_dark", height=250,
                                   margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_down, use_container_width=True)

st.divider()

# -----------------------------------------------------------------------
# Statistiques + Historique
# -----------------------------------------------------------------------

st.markdown('<p class="section-title">📈 Statistiques de trading</p>', unsafe_allow_html=True)
s1, s2, s3, s4, s5 = st.columns(5)
s1.metric("Total trades", stats.get("total", 0))
s2.metric("Gagnants",     stats.get("wins", 0))
s3.metric("Perdants",     stats.get("losses", 0))
s4.metric("Win rate",     f"{stats.get('win_rate', 0):.1f}%")
s5.metric("PnL total",    f"{stats.get('total_pnl_usd', 0):+.2f} USDT")

st.divider()
st.markdown('<p class="section-title">📋 Historique des trades</p>', unsafe_allow_html=True)

if trades:
    rows_hist = []
    for t in reversed(trades[-30:]):
        rows_hist.append({
            "Date entrée": t.entry_time,
            "Date sortie": t.exit_time or "—",
            "Crypto":      t.symbol,
            "Stratégie":   t.strategy,
            "Entrée":      f"{t.entry_price:,.4f}",
            "Sortie":      f"{t.exit_price:,.4f}" if t.exit_price else "—",
            "Raison":      t.exit_reason or "—",
            "PnL %":       f"{t.pnl_pct:+.2f}%" if t.pnl_pct is not None else "—",
            "PnL USDT":    f"{t.pnl_usd:+.4f}" if t.pnl_usd is not None else "—",
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
