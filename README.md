# SG-HK Quant Bot

A long-only quantitative trading bot built for the **SG vs HK University Web3 Quant Hackathon**.

The bot uses **Binance BTC/USDT market data** to generate signals from a **VWAP mean reversion strategy**, then sends **mock market orders** to the **Roostoo mock exchange**.

---

## 1. Project Overview

### Strategy summary
This bot trades BTC using a **VWAP mean reversion strategy**. It looks for situations where price deviates below a rolling VWAP-based lower band, then enters long positions in anticipation of a reversion back toward fair value.

### High-level idea
This is a **long-only mean reversion** strategy.

The core idea is:
- when BTC price falls meaningfully below its recent VWAP range, it may be temporarily undervalued
- the bot enters a long position when this deviation creates a bullish signal
- the bot exits when the signal weakens, when price reaches an exit threshold, or when stop-loss protection is triggered

### Key features
- VWAP-based long-only trading logic
- Dynamic position sizing based on target portfolio allocation
- Stop-loss risk management
- Position top-up logic when holdings are below target size
- Runtime state persistence across restarts
- Mock execution through Roostoo
- Activity and trade logging for traceability
- Backtesting support for evaluating performance on historical data

---

## 2. Architecture

### System design
The bot is structured as a modular pipeline:

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
- calculates rolling standard deviation
- builds entry and exit bands
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
- stores entry price
- stores stop-loss price

### Tech stack used
- **Python**
- **Pandas / NumPy** for data handling
- **Binance market data API** for historical candles
- **Roostoo mock exchange API** for simulated execution
- **JSON** for runtime state persistence

---

## 3. Strategy Explanation

### Signal construction
The strategy computes:
- a rolling **VWAP**
- a rolling **standard deviation of close**
- a **trend SMA** for trend regime filtering

The main bands are:
- **Lower band** = `VWAP - LOWER_STD_MULT × std`
- **Upper band** = `VWAP + EXIT_STD_MULT × std`
- **Strong upper band** = `VWAP + STRONG_EXIT_STD_MULT × std`

### Entry condition
The bot generates a long signal when:

- `close < lower_band`

This means price has moved sufficiently below rolling VWAP and may revert upward.

### Exit condition
The strategy exits differently depending on whether the market is in an uptrend.

#### Uptrend case
If:
- `close > trend_sma`

then the strategy treats the market as an uptrend and uses a wider exit threshold:

- exit when `close > strong_upper_band`

#### Non-uptrend case
If:
- `close <= trend_sma`

then the strategy uses the normal exit threshold:

- exit when `close > upper_band`

This means the strategy gives trades more room to run in stronger trend conditions, but exits earlier when the broader trend is weaker.

### Signal state
The signal is long / flat only:
- `1 = long`
- `0 = flat`

The bot does **not** short BTC.

### Live trading logic
The live bot evaluates the **latest closed candle**, not the current unfinished candle.

This is important because:
- it reduces noise from intrabar moves
- it avoids acting on incomplete candles
- it keeps live behaviour more consistent with backtesting

### Stop-loss logic
In addition to the strategy exit, the bot also applies a stop loss.

After a successful buy, it stores:

- `entry_price`
- `stop_loss_price = entry_price × (1 - STOP_LOSS_PCT)`

If the latest closed candle falls below the stored stop-loss price, the bot exits the position.

This gives the system two layers of exit logic:
- **strategy-based exit**
- **risk-based forced exit**

### Position sizing logic
The bot does **not** use a fixed BTC quantity per trade.

Instead, it sizes positions dynamically based on a target portfolio allocation:

1. estimate total portfolio equity
2. compute target notional exposure using `TARGET_ALLOC_PCT`
3. convert target notional into BTC quantity
4. round the quantity down to valid precision using `QTY_DECIMALS`
5. ensure the order respects `MIN_QTY`

This means the bot scales its position size with account value rather than always buying a fixed amount.

### Top-up logic
If the bot is already long and the signal remains bullish, it checks whether current BTC holdings are below the desired target allocation.

A top-up buy is triggered when current holdings are below the configured threshold:

- current holdings `< target_qty × TOP_UP_THRESHOLD_RATIO`

This allows the bot to rebalance toward the intended position size when:
- the account has drifted away from target allocation
- a prior partial reduction happened
- the bot restarts while already holding BTC

### Exit execution logic
On exit, the bot can either:
- close the full position, or
- apply a sell buffer if partial reduction is desired

This is controlled by:
- `CLOSE_FULL_POSITION_ON_EXIT`
- `SELL_BUFFER_RATIO`

For the hackathon version, full exits are usually the cleanest and safest setup.

### Assumptions made
- the strategy is **long-only**
- Binance candles are used as the source of market truth
- orders are executed as **mock market orders**
- execution occurs on **closed candles**, not tick-by-tick intrabar data
- the backtest is an approximation of live behaviour and does not fully model slippage, latency, fees, or partial fills

---

## 4. Configuration

All main runtime parameters are stored in:

```bash
bot/config/settings.py
