# Binance Trading Bot

Automated trading bot for Binance using RSI + MACD + EMA strategy with risk management.

## Features

- **Signals**: RSI, MACD, EMA (short/long), volume filter
- **Risk management**: automatic stop-loss (−2%) and take-profit (+4%)
- **Position persistence**: survives restarts via `positions.json`
- **Testnet support**: full Binance testnet integration
- **Backtest**: simulate the strategy on historical klines

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your API keys
```

### Get testnet API keys
1. Go to https://testnet.binance.vision
2. Log in with GitHub
3. Generate API keys
4. Paste them into `.env`

## Usage

### Backtest (no API keys needed)
```bash
python backtest.py --symbol BTCUSDT --interval 1h --limit 1000 --log
```

Options:
| Flag | Default | Description |
|------|---------|-------------|
| `--symbol` | BTCUSDT | Trading pair |
| `--interval` | 15m | Candle interval |
| `--limit` | 500 | Number of candles |
| `--capital` | 10000 | Initial capital ($) |
| `--sl` | 2.0 | Stop-loss % |
| `--tp` | 4.0 | Take-profit % |
| `--log` | off | Print trade log |

### Run the bot (testnet)
```bash
python main.py --mode testnet
```

### Run the bot (live) — real funds!
```bash
python main.py --mode live
```
You will be asked to confirm with `YES I UNDERSTAND` before any order is placed.

## Strategy

| Signal | Conditions |
|--------|-----------|
| **BUY** | RSI < 30 **AND** MACD bullish crossover **AND** EMA9 > EMA21 **AND** volume > 20-period avg |
| **SELL** | RSI > 70 **AND** MACD bearish crossover **AND** EMA9 < EMA21 |
| **HOLD** | anything else |

Stop-loss and take-profit are checked every poll cycle before the strategy signal.

## Configuration (`.env`)

```
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
SYMBOL=BTCUSDT
INTERVAL=15m
QUANTITY=0.001
STOP_LOSS_PCT=2.0
TAKE_PROFIT_PCT=4.0
LOG_LEVEL=INFO
```

## Files

```
trading_bot/
├── main.py              # entry point (--mode testnet|live)
├── backtest.py          # historical simulation
├── requirements.txt
├── .env.example
├── positions.json       # auto-created, tracks open position
├── trading.log          # auto-created, full log
└── bot/
    ├── config.py        # env-based config + logging setup
    ├── strategy.py      # RSI + MACD + EMA signals
    ├── risk_manager.py  # SL/TP + position persistence
    └── trader.py        # Binance client wrapper
```

## Disclaimer

This software is for educational purposes only. Cryptocurrency trading carries significant financial risk. Never trade with funds you cannot afford to lose.
