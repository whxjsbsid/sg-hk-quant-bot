# SG-HK Quant Bot

A simple quant trading bot built for the SG vs HK University Web3 Quant Hackathon.

This bot uses a **VWAP mean reversion strategy** on Binance market data and sends mock trades to the **Roostoo Mock Exchange API**.

## Strategy Overview

The current strategy is a **long-only VWAP reversion strategy**:

- Pull historical daily BTC price data from Binance
- Compute VWAP and trading bands
- Generate trading signals
- Place mock market orders through Roostoo when the signal changes

Current signal logic used in `main.py`:
- `0` = flat
- `1` = long

Trade actions:
- `0 -> 1` = BUY
- `1 -> 0` = SELL

## Features

- Binance historical kline data loader
- VWAP mean reversion signal generation
- Roostoo mock exchange integration
- Trade logging
- Activity logging
- Simple bot execution flow for testing and deployment

## Project Structure

```bash
bot/
│
├── main.py
├── execution/
│   └── roostoo_client.py
├── data/
│   └── binance_loader.py
├── strategy/
│   └── vwap_reversion.py
├── logs/
│   ├── trade_logger.py
│   └── activity_logger.py
│
├── requirements.txt
├── .env
└── README.md
