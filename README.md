# SG-HK Quant Bot

A simple quant trading bot built for the SG vs HK University Web3 Quant Hackathon.

This project uses Binance market data to generate trading signals based on a VWAP mean reversion strategy, then sends mock orders to the Roostoo mock exchange.

## Overview

The bot follows a simple long-only workflow:

- Load historical BTC price data from Binance
- Compute VWAP and signal bands
- Generate trading signals
- Detect signal changes
- Place mock market orders through Roostoo
- Log trades and bot activity

## Strategy

The current strategy is a VWAP mean reversion strategy.

Signal logic used in the bot:

- `0` = flat
- `1` = long

Trade logic:

- `0 -> 1` = BUY
- `1 -> 0` = SELL

This means the bot only enters and exits long positions for now.

## Project Structure

```bash
bot/
├── config/
│   └── settings.py
├── data/
│   └── binance_loader.py
├── execution/
│   └── roostoo_client.py
├── logs/
│   ├── activity_logger.py
│   └── trade_logger.py
├── strategy/
│   └── vwap_reversion.py
├── main.py
└── test_roostoo.py      # Simple Roostoo API smoke test that checks balance, places a mock market order, and queries orders

backtest.py              # Strategy backtesting script
requirements.txt
README.md
.gitignore
