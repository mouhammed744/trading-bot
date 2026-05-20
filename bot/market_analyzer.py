"""
Analyse globale du marche — tendance, confiance, recommandation d'achat.
"""
import pandas as pd
import ta
import logging

logger = logging.getLogger("trading_bot.market_analyzer")


class MarketAnalyzer:

    def analyze(self, df: pd.DataFrame) -> dict:
        """
        Analyse les conditions du marche et retourne un rapport complet.

        Returns:
            trend          : "BULL" | "BEAR" | "SIDEWAYS"
            confidence     : 0-100 (score de confiance)
            recommendation : "ACHETER" | "ATTENDRE" | "EVITER"
            reasons        : liste de raisons
        """
        df = df.copy()
        close = df["close"]

        df["ema50"]  = ta.trend.EMAIndicator(close, 50).ema_indicator()
        df["ema100"] = ta.trend.EMAIndicator(close, 100).ema_indicator()
        df["ema200"] = ta.trend.EMAIndicator(close, 200).ema_indicator()
        df["rsi"]    = ta.momentum.RSIIndicator(close, 14).rsi()
        df["atr"]    = ta.volatility.AverageTrueRange(
            df["high"], df["low"], df["close"], 14
        ).average_true_range()
        df["vol_ma20"] = df["volume"].rolling(20).mean()
        df["vol_ma5"]  = df["volume"].rolling(5).mean()

        df.dropna(inplace=True)
        if len(df) < 2:
            return {
                "trend": "INCONNU", "confidence": 0,
                "recommendation": "ATTENDRE",
                "reasons": ["Pas assez de donnees"],
                "price": 0, "rsi": 0, "ema50": 0, "ema200": 0, "atr_pct": 0,
            }

        c       = df.iloc[-1]
        price   = float(c["close"])
        ema50   = float(c["ema50"])
        ema100  = float(c["ema100"])
        ema200  = float(c["ema200"])
        rsi     = float(c["rsi"])
        atr     = float(c["atr"])
        vol_ma20 = float(c["vol_ma20"])
        vol_ma5  = float(c["vol_ma5"])

        score   = 0  # -100 a +100
        reasons = []

        # --- Tendance via EMAs ---
        if price > ema50 > ema100 > ema200:
            score += 40
            trend = "BULL"
            reasons.append("Tendance haussiere forte (prix > EMA50 > EMA100 > EMA200)")
        elif price > ema50 and price > ema200:
            score += 20
            trend = "BULL"
            reasons.append("Tendance haussiere moderee (prix au-dessus EMA50 et EMA200)")
        elif price < ema50 < ema100 < ema200:
            score -= 40
            trend = "BEAR"
            reasons.append("Tendance baissiere forte (prix < EMA50 < EMA100 < EMA200)")
        elif price < ema50 and price < ema200:
            score -= 20
            trend = "BEAR"
            reasons.append("Tendance baissiere moderee (prix sous EMA50 et EMA200)")
        else:
            trend = "SIDEWAYS"
            reasons.append("Marche lateral — pas de tendance claire")

        # --- RSI ---
        if rsi < 30:
            score += 25
            reasons.append(f"RSI survendu ({rsi:.0f}) — forte opportunite d'achat")
        elif 30 <= rsi < 45:
            score += 15
            reasons.append(f"RSI bas ({rsi:.0f}) — bon point d'entree potentiel")
        elif 45 <= rsi <= 60:
            score += 10
            reasons.append(f"RSI neutre ({rsi:.0f}) — conditions saines")
        elif 60 < rsi <= 70:
            score -= 5
            reasons.append(f"RSI eleve ({rsi:.0f}) — prudence")
        else:
            score -= 20
            reasons.append(f"RSI surachete ({rsi:.0f}) — risque de correction")

        # --- Volume ---
        if vol_ma5 > vol_ma20 * 1.5:
            score += 20
            reasons.append("Volume tres eleve — forte conviction des acheteurs")
        elif vol_ma5 > vol_ma20 * 1.2:
            score += 10
            reasons.append("Volume en hausse — confirmation de la tendance")
        elif vol_ma5 < vol_ma20 * 0.6:
            score -= 10
            reasons.append("Volume faible — tendance peu fiable")

        # --- Volatilite (ATR) ---
        atr_pct = (atr / price) * 100
        if atr_pct > 4:
            score -= 15
            reasons.append(f"Volatilite tres elevee ({atr_pct:.1f}%) — risque accru")
        elif atr_pct > 2:
            score -= 5
            reasons.append(f"Volatilite moderee ({atr_pct:.1f}%)")
        else:
            score += 5
            reasons.append(f"Volatilite faible ({atr_pct:.1f}%) — marche stable")

        # --- Recommandation ---
        confidence = min(100, max(0, (score + 100) / 2))

        if score >= 35 and trend != "BEAR":
            recommendation = "ACHETER"
        elif score <= -15 or trend == "BEAR":
            recommendation = "EVITER"
        else:
            recommendation = "ATTENDRE"

        return {
            "trend":          trend,
            "confidence":     round(confidence, 1),
            "recommendation": recommendation,
            "score":          score,
            "reasons":        reasons,
            "price":          round(price, 2),
            "rsi":            round(rsi, 1),
            "ema50":          round(ema50, 2),
            "ema200":         round(ema200, 2),
            "atr_pct":        round(atr_pct, 2),
        }

    def print_report(self, analysis: dict, balance_usdt: float = None):
        """Affiche un rapport lisible dans la console."""
        LINE = "=" * 62
        print(f"\n{LINE}")
        print("  ANALYSE DU MARCHE")
        print(LINE)
        print(f"  Prix actuel  : {analysis['price']} USDT")
        print(f"  Tendance     : {analysis['trend']}")
        print(f"  Confiance    : {analysis['confidence']}%")
        print(f"  RSI          : {analysis['rsi']}")
        print(f"  EMA50        : {analysis['ema50']}  |  EMA200 : {analysis['ema200']}")
        print(f"  Volatilite   : {analysis['atr_pct']}%")
        if balance_usdt is not None:
            print(f"  Solde USDT   : {balance_usdt:.2f} USDT")
        print()
        print("  Analyse :")
        for r in analysis["reasons"]:
            print(f"    • {r}")
        print()

        rec = analysis["recommendation"]
        if rec == "ACHETER":
            print("  >>> C'EST LE MOMENT D'ACHETER !")
            if balance_usdt is not None:
                if balance_usdt < 10:
                    print(f"  >>> MAIS votre solde est trop bas ({balance_usdt:.2f} USDT).")
                    print("  >>> Rechargez votre portefeuille Binance pour que le bot puisse trader.")
                else:
                    print(f"  >>> Vous avez {balance_usdt:.2f} USDT — le bot va executer l'ordre.")
        elif rec == "EVITER":
            print("  >>> EVITER — le marche est defavorable, pas de trade.")
        else:
            print("  >>> ATTENDRE — conditions neutres, surveiller le marche.")

        print(f"{LINE}\n")
        logger.info(
            "Analyse marche: tendance=%s confiance=%.0f%% reco=%s rsi=%.1f",
            analysis["trend"], analysis["confidence"], rec, analysis["rsi"]
        )
