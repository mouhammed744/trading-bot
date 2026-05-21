import os
import logging
from dotenv import load_dotenv

load_dotenv()

# API credentials
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# Trading parameters
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
INTERVAL = os.getenv("INTERVAL", "15m")
QUANTITY = float(os.getenv("QUANTITY", "0.001"))

# Risk management
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "2.0"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "4.0"))

# Balance management
MIN_USDT_BALANCE = float(os.getenv("MIN_USDT_BALANCE", "10.0"))
TRADE_BALANCE_PCT = float(os.getenv("TRADE_BALANCE_PCT", "0.1"))  # 10% max par trade

# Trailing stop loss
TRAILING_SL_ENABLED = os.getenv("TRAILING_SL_ENABLED", "true").lower() == "true"
TRAILING_SL_PCT = float(os.getenv("TRAILING_SL_PCT", "1.5"))

# Multi-crypto portfolio
MAX_POSITIONS      = int(os.getenv("MAX_POSITIONS", "10"))
SCAN_INTERVAL      = int(os.getenv("SCAN_INTERVAL", "300"))
MULTI_CRYPTO       = os.getenv("MULTI_CRYPTO", "true").lower() == "true"

# Seuils de signal adaptatifs
# SIGNAL_THRESHOLD_LOW  : 1 stratégie suffit si c'est la meilleure (avec historique prouvé)
# SIGNAL_THRESHOLD_HIGH : 3 stratégies requises en temps normal
SIGNAL_THRESHOLD      = float(os.getenv("SIGNAL_THRESHOLD",      "0.43"))  # rétro-compat
SIGNAL_THRESHOLD_LOW  = float(os.getenv("SIGNAL_THRESHOLD_LOW",  "0.14"))  # 1/7 stratégies
SIGNAL_THRESHOLD_HIGH = float(os.getenv("SIGNAL_THRESHOLD_HIGH", "0.43"))  # 3/7 stratégies

# Technical indicators
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EMA_SHORT = 9
EMA_LONG = 21
VOLUME_MA_PERIOD = 20

# Files
POSITIONS_FILE = "positions.json"
LOG_FILE = "trading.log"

# Testnet URLs
TESTNET_BASE_URL = "https://testnet.binance.vision/api"
TESTNET_STREAM_URL = "wss://testnet.binance.vision/ws"


def setup_logging(log_level: str = None):
    level = getattr(logging, (log_level or os.getenv("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("trading_bot")


def validate_config():
    errors = []
    if not API_KEY:
        errors.append("BINANCE_API_KEY is not set")
    if not API_SECRET:
        errors.append("BINANCE_API_SECRET is not set")
    if QUANTITY <= 0:
        errors.append("QUANTITY must be positive")
    if STOP_LOSS_PCT <= 0 or STOP_LOSS_PCT >= 100:
        errors.append("STOP_LOSS_PCT must be between 0 and 100")
    if TRADE_BALANCE_PCT > 0.25:
        errors.append("TRADE_BALANCE_PCT > 25% est dangereux — valeur recommandee: 0.05 a 0.10")
    if TAKE_PROFIT_PCT <= 0 or TAKE_PROFIT_PCT >= 100:
        errors.append("TAKE_PROFIT_PCT must be between 0 and 100")
    return errors
