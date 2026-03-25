# SG-HK Quant Bot

A long-only quantitative trading bot built for the **SG vs HK University Web3 Quant Hackathon**.

The system uses **Binance market data** to generate **VWAP mean reversion signals** and sends **mock market orders** to the **Roostoo mock exchange**. It now supports **multiple coins** in one portfolio, with **per-coin target allocations** such as BTC 25%, ETH 25%, and SOL 25%.

---

## 1. Project Overview

### Strategy summary
This bot applies a **VWAP mean reversion strategy** across multiple crypto assets. It looks for situations where price falls sufficiently below a rolling VWAP-based lower band, enters long positions, and exits when price reverts upward, the signal weakens, or stop-loss protection is triggered.

### High-level idea
This is a **long-only multi-asset portfolio bot**.

The core idea is:
- detect coins that are temporarily trading below rolling VWAP-based fair value
- enter long positions when a bullish mean reversion signal appears
- size each coin using its own **target portfolio allocation**
- exit on signal reversal or stop loss
- rebalance toward target size using top-up logic when needed

### Key features
- VWAP-based long-only trading logic
- Multi-coin portfolio support
- Per-coin target allocation sizing
- Shared cash pool across all configured markets
- Stop-loss risk management
- Top-up logic when holdings fall below target size
- Runtime state persistence across restarts
- Mock execution through Roostoo
- Activity and trade logging for traceability
- Multi-coin backtesting support

---

## 2. Architecture

### System design
The bot is structured as a modular pipeline:

**Binance market data → signal generation → portfolio sizing / risk checks → Roostoo mock execution → logging + runtime state persistence**

### Main components

#### Data module
Responsible for pulling historical OHLCV candle data from Binance.

- loads market data for each configured symbol
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

- sizes positions using **total portfolio equity**
- applies **per-coin target allocation**
- submits mock market orders to Roostoo
- handles top-up buys when a coin is below target size
- handles exits on signal reversal or stop loss

#### Logging module
Responsible for observability and debugging.

- records activity logs to `bot/logs/bot.log`
- records trade logs to `bot/logs/trades.csv`
- includes pair-level trade details for multi-coin monitoring

#### Runtime state module
Responsible for maintaining continuity across restarts.

For each configured market, it stores:
- last processed candle
- current position state
- entry price
- stop-loss price

---

## 3. Strategy Explanation

### Signal construction
For each configured coin, the strategy computes:
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

### Signal state
The signal is long / flat only:
- `1 = long`
- `0 = flat`

The bot does **not** short crypto.

### Live trading logic
The live bot evaluates the **latest closed candle**, not the unfinished candle.

This is important because:
- it reduces noise from intrabar moves
- it avoids acting on incomplete candles
- it keeps live behaviour more consistent with backtesting

---

## 4. Portfolio Sizing Logic

### Per-coin target allocation
Each market has its own `target_alloc_pct`.

Example:
- BTC = 25%
- ETH = 25%
- SOL = 25%

This means each coin independently targets that fraction of **total portfolio equity**.

### Total portfolio equity
Sizing is based on:

- available quote currency balance
- plus the market value of all configured base-coin holdings

This is important because each coin should size itself against the **same portfolio base**, not just the remaining leftover cash.

### Entry sizing
For each market:

1. compute total portfolio equity
2. compute target notional for that coin using `target_alloc_pct`
3. convert target notional into quantity
4. round down using `QTY_DECIMALS`
5. ensure quantity respects `MIN_QTY`

So:

`target_qty = (total_portfolio_equity × target_alloc_pct) / coin_price`

### Top-up logic
If the bot is already long and the signal remains bullish, it checks whether holdings are below target size.

A top-up buy is triggered when:

`current_base_qty < target_qty × TOP_UP_THRESHOLD_RATIO`

This allows the bot to rebalance back toward intended allocation.

### Exit execution logic
On exit, the bot can either:
- close the full position, or
- reduce by a sell buffer

This is controlled by:
- `CLOSE_FULL_POSITION_ON_EXIT`
- `SELL_BUFFER_RATIO`

For the hackathon version, full exits are usually the cleanest setup.

### Stop-loss logic
After a successful buy, the bot stores:

- `entry_price`
- `stop_loss_price = entry_price × (1 - STOP_LOSS_PCT)`

If the latest closed candle falls below the stored stop-loss price, the bot exits the position.

---

## 5. Configuration

All main runtime parameters are stored in:

```bash
bot/config/settings.py
