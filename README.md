# SG-HK Quant Bot

A long-only quantitative trading bot built for the **SG vs HK University Web3 Quant Hackathon**.

The bot uses **Binance BTC/USDT market data** to generate signals from a **VWAP mean reversion strategy**, then sends **mock market orders** to the **Roostoo mock exchange**. 

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

### Prerequisites
Before running the bot, ensure you have:
- Python 3.10 or above
- `pip` installed
- internet access for Binance market data
- valid Roostoo mock trading credentials set in your environment if required by your setup

### Step 1: Clone the repository

~~~bash
git clone <your-repo-url>
cd sg-hk-quant-bot
~~~

### Step 2: Install dependencies

~~~bash
pip install -r requirements.txt
~~~

### Step 3: Configure the bot

Update the main configuration file at:

~~~bash
bot/config/settings.py
~~~

Example configuration:

~~~python
BINANCE_SYMBOL = "BTCUSDT"
ROOSTOO_PAIR = "BTC/USD"
INTERVAL = "15m"
LIMIT = 3000
VWAP_WINDOW = 20
LOWER_STD_MULT = 1.75
STRONG_EXIT_STD_MULT = 2.5
TREND_WINDOW = 48
INITIAL_CASH = 50000
POLL_SECONDS = 60
BASE_COIN = "BTC"
TARGET_ALLOC_PCT = 0.30
MIN_QTY = 0.001
MAX_QTY = 10.0
QTY_DECIMALS = 4
SELL_BUFFER_RATIO = 0.999
STOP_LOSS_PCT = 0.05
TOP_UP_THRESHOLD_RATIO = 0.95
~~~

If your Roostoo client requires API credentials, export them before running the bot:

~~~bash
export ROOSTOO_API_KEY=your_key_here
export ROOSTOO_API_SECRET=your_secret_here
~~~

### Step 4: Run the live bot

~~~bash
python3 -m bot.main
~~~

The live bot will:
- fetch the latest Binance candles
- compute VWAP and trading signals
- check the latest closed candle
- determine whether to buy, top up, sell, or stop out
- place mock market orders through Roostoo
- save runtime state and write logs for monitoring

### Step 5: Run the backtest

~~~bash
python3 backtest.py
~~~

The backtest uses historical Binance data and prints key metrics such as:
- total return
- buy-and-hold return
- max drawdown
- Sharpe ratio
- Sortino ratio
- Calmar ratio
- trade count
- stop-loss exit count

### Step 6: Runtime files

When the bot runs, it may automatically create:
- `bot/runtime_state.json` to persist live position state across restarts
- log files for bot activity and trade history

These files are generated locally during execution and do not need to be manually created.

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
│   └── main.py
├── backtest.py
└── README.md
