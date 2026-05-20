import logging
import time
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException
from bot import config

logger = logging.getLogger("trading_bot.trader")


_LIVE_ENDPOINTS = [
    "https://api.binance.com/api",
    "https://api1.binance.com/api",
    "https://api2.binance.com/api",
    "https://api3.binance.com/api",
    "https://api-gcp.binance.com/api",
]

def _make_client(testnet: bool) -> Client:
    if testnet:
        client = Client(config.API_KEY, config.API_SECRET)
        client.API_URL = config.TESTNET_BASE_URL
        return client
    for endpoint in _LIVE_ENDPOINTS:
        try:
            client = Client(config.API_KEY, config.API_SECRET)
            client.API_URL = endpoint
            client.ping()
            logger.info("Binance connecte via %s", endpoint)
            return client
        except Exception:
            logger.warning("Endpoint inaccessible: %s", endpoint)
    raise ConnectionError("Aucun endpoint Binance accessible")


class Trader:
    def __init__(self, testnet: bool = True):
        self.testnet = testnet
        self.client = _make_client(testnet)
        self.symbol = config.SYMBOL
        self.interval = config.INTERVAL
        self.quantity = config.QUANTITY
        logger.info(
            "Trader initialise — symbol=%s interval=%s testnet=%s",
            self.symbol, self.interval, testnet,
        )

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_klines(self, limit: int = 200, interval: str = None, symbol: str = None) -> pd.DataFrame:
        raw = self.client.get_klines(
            symbol=symbol or self.symbol,
            interval=interval or self.interval,
            limit=limit,
        )
        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "num_trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ])
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col])
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        return df

    def get_ticker_price(self, symbol: str = None) -> float:
        ticker = self.client.get_symbol_ticker(symbol=symbol or self.symbol)
        return float(ticker["price"])

    def get_account_balance(self, asset: str = "USDT") -> float:
        info = self.client.get_account()
        for bal in info["balances"]:
            if bal["asset"] == asset:
                return float(bal["free"])
        return 0.0

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def place_market_buy(self, quantity: float = None, symbol: str = None) -> dict:
        sym = symbol or self.symbol
        qty = quantity if quantity is not None else self.quantity
        logger.info("MARKET BUY — %s qty=%.6f", sym, qty)
        try:
            order = self.client.order_market_buy(symbol=sym, quantity=qty)
            logger.info("BUY rempli: %s", order.get("orderId"))
            return order
        except BinanceAPIException as exc:
            logger.error("BUY echoue (%s): %s", sym, exc)
            raise

    def place_market_sell(self, quantity: float = None, symbol: str = None) -> dict:
        sym = symbol or self.symbol
        qty = quantity if quantity is not None else self.quantity
        logger.info("MARKET SELL — %s qty=%.6f", sym, qty)
        try:
            order = self.client.order_market_sell(symbol=sym, quantity=qty)
            logger.info("SELL rempli: %s", order.get("orderId"))
            return order
        except BinanceAPIException as exc:
            logger.error("SELL echoue (%s): %s", sym, exc)
            raise

    def get_filled_price(self, order: dict) -> float:
        fills = order.get("fills", [])
        if fills:
            total_qty = sum(float(f["qty"]) for f in fills)
            total_cost = sum(float(f["price"]) * float(f["qty"]) for f in fills)
            return total_cost / total_qty if total_qty else 0.0
        return float(order.get("price", 0))

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        try:
            self.client.ping()
            return True
        except Exception as exc:
            logger.error("Ping echoue: %s", exc)
            return False

    def get_server_time_offset_ms(self) -> int:
        server_ts = self.client.get_server_time()["serverTime"]
        local_ts = int(time.time() * 1000)
        return server_ts - local_ts
