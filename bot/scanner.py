"""
Scanner multi-cryptos — analyse toutes les paires USDT de Binance
et retourne les meilleures opportunites de trading.
"""
import logging
import re
import time
from typing import List, Dict

logger = logging.getLogger("trading_bot.scanner")

MIN_VOLUME_USDT = 2_000_000
MAX_SYMBOLS     = 200

_VALID_SYMBOL = re.compile(r'^[A-Z0-9]{2,15}USDT$')

def _is_safe_symbol(symbol: str) -> bool:
    return bool(_VALID_SYMBOL.match(symbol))


class Scanner:
    def __init__(self, trader):
        self.trader = trader
        self._symbols_cache: List[str] = []
        self._cache_time: float = 0
        self._cache_ttl: int = 300  # rafraichit la liste toutes les 5 minutes

    # ------------------------------------------------------------------

    def get_liquid_symbols(self) -> List[str]:
        """Retourne les paires USDT les plus liquides sur Binance."""
        now = time.time()
        if self._symbols_cache and (now - self._cache_time) < self._cache_ttl:
            return self._symbols_cache

        try:
            tickers = self.trader.client.get_ticker()
        except Exception as exc:
            logger.error("Impossible de recuperer les tickers: %s", exc)
            return self._symbols_cache or []

        usdt_pairs = [
            t for t in tickers
            if _is_safe_symbol(t["symbol"])              # format strict [A-Z0-9]+USDT
            and not t["symbol"].endswith("UPUSDT")       # leveraged tokens
            and not t["symbol"].endswith("DOWNUSDT")
            and not t["symbol"].endswith("BULLUSDT")
            and not t["symbol"].endswith("BEARUSDT")
            and float(t.get("quoteVolume", 0)) >= MIN_VOLUME_USDT
        ]

        usdt_pairs.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        symbols = [t["symbol"] for t in usdt_pairs[:MAX_SYMBOLS]]

        self._symbols_cache = symbols
        self._cache_time = now
        logger.info("Scanner: %d paires USDT liquides trouvees", len(symbols))
        return symbols

    def scan(self, strategy_mgr, limit: int = 200, interval: str = None) -> List[Dict]:
        """
        Analyse toutes les paires liquides avec les strategies.
        Retourne la liste des opportunites triees par force du signal BUY.
        """
        symbols = self.get_liquid_symbols()
        opportunities = []
        errors = 0

        logger.info("Scan en cours sur %d paires...", len(symbols))

        for symbol in symbols:
            try:
                df = self.trader.get_klines(limit=limit, interval=interval, symbol=symbol)
                result = strategy_mgr.get_signal(df)

                if result["signal"] == "BUY":
                    price = float(df["close"].iloc[-1])
                    vol_24h = float(df["volume"].iloc[-20:].sum())
                    opportunities.append({
                        "symbol":   symbol,
                        "price":    price,
                        "buy_pct":  result["buy_pct"],
                        "signal":   result["signal"],
                        "details":  result["details"],
                        "vol_24h":  vol_24h,
                    })
                    logger.debug("BUY signal: %s (%.0f%%)", symbol, result["buy_pct"])

                # Petite pause pour eviter le rate limit Binance
                time.sleep(0.05)

            except Exception as exc:
                errors += 1
                logger.debug("Erreur scan %s: %s", symbol, exc)

        # Trier par force du consensus BUY decroissant
        opportunities.sort(key=lambda x: x["buy_pct"], reverse=True)
        logger.info(
            "Scan termine: %d opportunites BUY sur %d paires (%d erreurs)",
            len(opportunities), len(symbols), errors,
        )
        return opportunities
