import logging
import time
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException
from bot import config

logger = logging.getLogger("trading_bot.trader")


def _make_client(testnet: bool) -> Client:
    client = Client(config.API_KEY, config.API_SECRET)
    if testnet:
        client.API_URL = config.TESTNET_BASE_URL
    return client


class Trader:
    def __init__(self, testnet: bool = True):
        self.testnet = testnet
        self.client = _make_client(testnet)
        self.symbol = config.SYMBOL
        self.interval = config.INTERVAL
        self.quantity = config.QUANTITY
        logger.info(
            "Trader initialised — symbol=%s interval=%s testnet=%s",
            self.symbol, self.interval, testnet,
        )

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_klines(self, limit: int = 200, interval: str = None) -> pd.DataFrame:
        """Fetch OHLCV klines and return a clean DataFrame."""
        raw = self.client.get_klines(
            symbol=self.symbol,
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

    def get_ticker_price(self) -> float:
        ticker = self.client.get_symbol_ticker(symbol=self.symbol)
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

    def place_market_buy(self, quantity: float = None) -> dict:
        qty = quantity if quantity is not None else self.quantity
        logger.info("Placing MARKET BUY — %s qty=%.5f", self.symbol, qty)
        try:
            order = self.client.order_market_buy(
                symbol=self.symbol,
                quantity=qty,
            )
            logger.info("BUY order filled: %s", order)
            return order
        except BinanceAPIException as exc:
            logger.error("BUY order failed: %s", exc)
            raise

    def place_market_sell(self, quantity: float = None) -> dict:
        qty = quantity if quantity is not None else self.quantity
        logger.info("Placing MARKET SELL — %s qty=%.5f", self.symbol, qty)
        try:
            order = self.client.order_market_sell(
                symbol=self.symbol,
                quantity=qty,
            )
            logger.info("SELL order filled: %s", order)
            return order
        except BinanceAPIException as exc:
            logger.error("SELL order failed: %s", exc)
            raise

    def get_filled_price(self, order: dict) -> float:
        """Extract average fill price from an order response."""
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
            logger.error("Ping failed: %s", exc)
            return False

    def get_server_time_offset_ms(self) -> int:
        server_ts = self.client.get_server_time()["serverTime"]
        local_ts = int(time.time() * 1000)
        return server_ts - local_ts
