# SG-HK Quant Bot

A simple quantitative trading bot built for the **SG vs HK University Web3 Quant Hackathon**.

This project uses **Binance market data** to generate trading signals based on a **VWAP mean reversion strategy**, then sends **mock market orders** to the **Roostoo mock exchange**.

## Overview

The bot follows a simple long-only workflow:

- Load historical BTC price data from Binance
- Compute rolling VWAP, volatility bands, and trend filter
- Generate long/flat trading signals
- Detect signal changes using the latest closed candle
- Place mock market orders through Roostoo
- Log trades and bot activity

## Strategy

The current strategy is a **long-only VWAP mean reversion strategy**.

Signal states used in the bot:

- `0` = flat
- `1` = long

Trade logic:

- `0 -> 1` = **BUY**
- `1 -> 0` = **SELL**

This means the bot only enters and exits long positions for now.

### Entry Logic
The bot enters a long position when price drops below the lower VWAP band, suggesting a possible short-term mean reversion opportunity.

### Exit Logic
The bot exits a long position when:
- price rises above the strong upper band during an uptrend, or
- price rises back above VWAP when the broader trend is weaker

## Key Features

- Uses **Binance kline data** as the market data source
- Supports fetching more than 1000 candles through pagination
- Evaluates signals using the **latest closed candle** to avoid trading on incomplete candles
- Sends mock orders to the **Roostoo mock exchange**
- Performs balance checks before placing orders
- Verifies order outcome using order responses, order queries, and post-trade balances
- Logs bot activity and trade history for debugging and review

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
└── test_roostoo.py      # Simple Roostoo API smoke test

backtest.py              # Strategy backtesting script
requirements.txt
README.md
.gitignore
