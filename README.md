# SG-HK Quant Bot

A long-only quantitative trading bot built for the **SG vs HK University Web3 Quant Hackathon**.

The bot uses **Binance BTC/USDT market data** to generate signals from a **VWAP mean reversion strategy**, then sends **mock market orders** to the **Roostoo mock exchange**. It is designed to be simple, transparent, and easy for judges to understand and reproduce.

---

## 1. Project Overview

### Strategy summary
This bot trades BTC using a **VWAP mean reversion strategy**. It looks for situations where price deviates below a rolling VWAP-based lower band, then enters long positions in anticipation of a reversion back toward fair value.

### High-level idea
This is a **mean reversion** strategy.

The core idea is:
- when BTC price falls meaningfully below its recent VWAP range, it may be temporarily undervalued
- the bot enters a long position when this deviation creates a bullish signal
- the bot exits when the signal weakens, when price reaches an exit condition, or when stop-loss protection is triggered

### Key features
- VWAP-based long-only trading logic
- Dynamic position sizing based on portfolio allocation
- Stop-loss risk management
- Position top-up logic when holdings are below target size
- Runtime state persistence across restarts
- Mock execution through Roostoo
- Activity and trade logging for traceability
- Backtesting support for evaluating performance on historical data

---

## 2. Architecture

### System design
The bot is structured as a simple modular pipeline:

**Binance market data → signal generation → position sizing / risk checks → Roostoo mock execution → logging + runtime state persistence**

### Main components

#### Data module
Responsible for pulling historical OHLCV candle data from Binance.

- loads BTC/USDT market data
- provides the historical price series used by the strategy
- refreshes data on each polling cycle

#### Strategy module
Responsible for computing indicators and signals.

- calculates rolling VWAP
- computes lower and upper signal bands
- generates long / flat signals based on mean reversion logic

#### Execution module
Responsible for converting signals into orders.

- sizes positions using target portfolio allocation
- submits mock market orders to Roostoo
- handles top-up buys when position size is below target
- handles exits on signal reversal or stop loss

#### Logging module
Responsible for observability and debugging.

- records activity logs
- records trade logs
- helps track strategy decisions and execution outcomes

#### Runtime state module
Responsible for maintaining continuity across restarts.

- stores last processed candle
- stores current position state
- stores entry price and stop-loss price

### Tech stack used
- **Python**
- **Pandas / NumPy** for data handling
- **Binance market data API** for historical candles
- **Roostoo mock exchange API** for simulated execution
- **JSON** for runtime state persistence

---

## 3. Strategy Explanation

### Entry conditions
The bot enters a long position when the strategy generates a bullish signal.

At a high level:
- price trades below a VWAP-based lower band
- the model interprets this as a potential mean reversion opportunity
- the bot buys BTC when the signal changes from flat to long, or tops up an existing position if it is underweight relative to the target allocation

### Exit conditions
The bot exits a long position when either of the following happens:

1. **Signal-based exit**  
   The strategy signal turns from long back to flat.

2. **Stop-loss exit**  
   The latest closed candle falls below the stored stop-loss price.

This creates two layers of exit logic:
- strategy-based exit
- risk-based forced exit

### Risk management rules
The bot includes explicit risk controls:

- **Long-only strategy**  
  The bot does not short BTC.

- **Stop-loss protection**  
  After a successful buy, the bot stores an entry price and computes a stop-loss price using:

  `stop_loss_price = entry_price × (1 - STOP_LOSS_PCT)`

- **Closed-candle confirmation**  
  Stop-loss and signal decisions are evaluated using closed candles rather than intrabar noise.

- **Order size limits**  
  Position quantities respect configured minimum and maximum size constraints.

- **Sell buffering**  
  A sell buffer ratio can be used to reduce the risk of overselling due to precision or balance mismatch.

### Position sizing logic
The bot does **not** rely on a fixed quantity per trade. Instead, it sizes positions dynamically using a target portfolio allocation.

The sizing logic works as follows:
1. estimate available portfolio value
2. compute target notional exposure using `TARGET_ALLOC_PCT`
3. convert target notional into BTC quantity
4. round the quantity to valid exchange precision
5. apply `MIN_QTY` and `MAX_QTY` rules

This means the bot scales its position size with account value instead of always buying a fixed amount like `0.01 BTC`.

### Top-up logic
If the bot is already long and the signal remains bullish, it checks whether the current BTC holdings are below the target allocation.

If the current position is below the configured threshold, the bot places a **top-up buy** to bring exposure back toward target size.

This is useful when:
- an old position is smaller than intended
- previous sells left a residual holding
- the bot restarts while already holding BTC

### Assumptions made
- the strategy is **long-only**
- Binance candles are used as the source of market truth
- orders are executed as **mock market orders**
- execution occurs on **closed candles**, not tick-by-tick intrabar data
- the backtest is an approximation of live behavior and may not perfectly capture slippage, latency, or partial fill behaviour

---

## 4. Setup Instructions & How to Run the Bot

### Project structure

```bash
sg-hk-quant-bot/
├── bot/
│   ├── config/
│   │   └── settings.py
│   ├── data/
│   │   └── binance_loader.py
│   ├── execution/
│   │   └── roostoo_client.py
│   ├── logs/
│   │   ├── activity_logger.py
│   │   └── trade_logger.py
│   ├── strategy/
│   │   └── vwap_reversion.py
│   ├── main.py
│   └── runtime_state.json
├── backtest.py
└── README.md
