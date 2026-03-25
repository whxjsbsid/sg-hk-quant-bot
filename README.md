# SG-HK Quant Bot

A long-only quantitative trading bot built for the **SG vs HK University Web3 Quant Hackathon**.

The system uses **Binance market data** to generate **VWAP mean reversion signals** and sends **mock market orders** to the **Roostoo mock exchange**. It supports **multiple coins** in one portfolio, with **per-coin target allocations**.

---

## 1. Project Overview

### Strategy summary
This bot implements a **VWAP mean reversion strategy** across multiple crypto assets. It identifies coins trading sufficiently below a rolling VWAP-based fair-value band, enters long positions when a mean reversion setup appears, and exits when price reverts upward, the signal weakens, or stop-loss protection is triggered.

### High-level idea
This is a **long-only multi-asset portfolio bot**.

The core idea is to:
- detect coins temporarily trading below rolling VWAP-based fair value
- enter long positions when a bullish mean reversion setup appears
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

## 2. Repository Structure

```text
repo/
├── bot/
│   ├── config/
│   │   └── settings.py              # Centralised strategy, portfolio, and execution parameters
│   ├── data/
│   │   └── binance_loader.py        # Binance market data loader used by live trading and backtesting
│   ├── execution/
│   │   └── roostoo_client.py        # Wrapper for Roostoo mock exchange requests
│   ├── logs/
│   │   ├── activity_logger.py       # Runtime activity and diagnostic logging
│   │   └── trade_logger.py          # Structured trade logging for fills, PnL, and strategy state
│   ├── strategy/
│   │   └── vwap_reversion.py        # Core VWAP mean reversion signal logic
│   └── main.py                      # Live trading entry point
├── .gitignore                       # Ignore logs, cache files, and local environment files
├── README.md                        # Project documentation and usage guide
├── backtest.py                      # Historical backtest entry point
└── requirements.txt                 # Python dependencies
```

This structure keeps the repository modular and easy to review: configuration, data loading, execution, logging, and strategy logic are separated so the trading flow is clear and maintainable.

---

## 3. Architecture

### System design
The bot follows a modular pipeline:

**Binance market data → signal generation → portfolio sizing / risk checks → Roostoo mock execution → logging + runtime state persistence**

### Main components

#### Data layer
Responsible for pulling historical OHLCV candle data from Binance.

- loads market data for each configured symbol
- provides the historical price series used by the strategy
- refreshes data on each polling cycle

#### Strategy layer
Responsible for computing indicators and signals.

- calculates rolling VWAP
- calculates rolling standard deviation
- calculates trend SMA for trend filtering
- builds entry and exit bands
- generates long / flat signals based on mean reversion logic

#### Execution layer
Responsible for converting signals into orders.

- sizes positions using **total portfolio equity**
- applies **per-coin target allocation**
- submits mock market orders to Roostoo
- handles top-up buys when a coin is below target size
- handles exits on signal reversal or stop loss

#### Logging layer
Responsible for observability and debugging.

- records activity logs to `bot/logs/bot.log`
- records trade logs to `bot/logs/trades.csv`
- stores strategy context for each execution decision

#### Runtime state layer
Responsible for maintaining continuity across restarts.

For each configured market, it stores:
- last processed candle timestamp
- current position state
- entry price
- stop-loss price
- last known strategy state if required

---

## 4. Strategy Explanation

### Core logic
The strategy assumes that when price deviates significantly below rolling VWAP, there is a chance of **short-term upward reversion** toward fair value.

The bot is **long-only**. It does not short crypto.

### Indicators used
For each configured coin, the strategy computes:
- a rolling **VWAP**
- a rolling **standard deviation of close**
- a rolling **trend SMA**

### Trading bands
The main bands are:

- **Lower band** = `VWAP - LOWER_STD_MULT × std`
- **Upper band** = `VWAP + EXIT_STD_MULT × std`
- **Strong upper band** = `VWAP + STRONG_EXIT_STD_MULT × std`

These bands define when the bot considers price sufficiently stretched for entry or exit.

### Entry condition
The bot generates a long signal when:

```text
close < lower_band
```

This means price has moved materially below rolling VWAP and may revert upward.

### Exit condition
The strategy uses a slightly different exit rule depending on the market regime.

#### Uptrend case
If:

```text
close > trend_sma
```

then the market is treated as being in an uptrend, and the strategy allows a wider exit threshold:

```text
exit when close > strong_upper_band
```

#### Non-uptrend case
If:

```text
close <= trend_sma
```

then the strategy uses the normal exit threshold:

```text
exit when close > upper_band
```

### Signal state
Signals are represented as:
- `1 = long`
- `0 = flat`

### Live-trading behaviour
The live bot evaluates the **latest closed candle**, not the unfinished candle.

This is important because it:
- reduces noise from intrabar moves
- avoids acting on incomplete price information
- keeps live behaviour more consistent with backtesting

---

## 5. Portfolio Sizing and Risk Management

### Per-coin target allocation
Each market has its own `target_alloc_pct`.

Example:
- BTC = 25%
- ETH = 25%
- SOL = 25%

Each coin independently targets that fraction of **total portfolio equity**.

### Total portfolio equity
Sizing is based on:
- available quote currency balance
- plus the marked-to-market value of all configured base-coin holdings

This ensures every coin sizes itself against the **same portfolio base**, rather than just remaining idle cash.

### Entry sizing
For each market, the bot:
1. computes total portfolio equity
2. computes target notional using `target_alloc_pct`
3. converts target notional into quantity
4. rounds down using `QTY_DECIMALS`
5. ensures quantity respects `MIN_QTY`

Formula:

```text
target_qty = (total_portfolio_equity × target_alloc_pct) / current_price
```

### Top-up logic
If the bot is already long and the signal remains bullish, it checks whether holdings are below target size.

A top-up buy is triggered when:

```text
current_base_qty < target_qty × TOP_UP_THRESHOLD_RATIO
```

This allows the portfolio to rebalance back toward intended exposure.

### Exit execution logic
On exit, the bot can either:
- close the full position, or
- reduce by a sell buffer

This behaviour is controlled by:
- `CLOSE_FULL_POSITION_ON_EXIT`
- `SELL_BUFFER_RATIO`

For a clean hackathon submission, full exits are usually the clearest behaviour.

### Stop-loss logic
After a successful buy, the bot stores:
- `entry_price`
- `stop_loss_price = entry_price × (1 - STOP_LOSS_PCT)`

If the latest closed candle falls below the stored stop-loss price, the bot exits the position.

### Risk controls summary
The main controls are:
- long-only exposure
- per-coin target allocation caps
- minimum tradable quantity checks
- stop-loss exits
- top-up threshold control
- optional full-position exit behaviour
- runtime state persistence to avoid duplicated signals after restart

---

## 6. Configuration

All main runtime parameters are stored in:

```bash
bot/config/settings.py
```

Typical parameters include:

| Parameter | Purpose |
|---|---|
| `VWAP_WINDOW` | Rolling window for VWAP calculation |
| `LOWER_STD_MULT` | Entry threshold below VWAP |
| `EXIT_STD_MULT` | Standard exit threshold above VWAP |
| `STRONG_EXIT_STD_MULT` | Wider exit threshold used in uptrends |
| `TREND_WINDOW` | Window for trend SMA |
| `STOP_LOSS_PCT` | Stop-loss percentage from entry price |
| `TOP_UP_THRESHOLD_RATIO` | Threshold for triggering top-up buys |
| `QTY_DECIMALS` | Quantity rounding precision |
| `MIN_QTY` | Minimum tradable quantity |
| `CLOSE_FULL_POSITION_ON_EXIT` | Whether to fully close positions on exit |
| `SELL_BUFFER_RATIO` | Optional sell reduction buffer |
| `SYMBOLS` / market config | List of traded markets and their allocations |

### Example market configuration
```python
MARKETS = [
    {"symbol": "BTCUSDT", "target_alloc_pct": 0.25},
    {"symbol": "ETHUSDT", "target_alloc_pct": 0.25},
    {"symbol": "SOLUSDT", "target_alloc_pct": 0.25},
]
```

---

## 7. Installation

### 1. Clone the repository
```bash
git clone <your-repo-url>
cd <your-repo-folder>
```

### 2. Create a virtual environment
```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows:
```bash
.venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

---

## 8. Environment Setup

Create a `.env` file in the project root using `.env.example` as reference.

Example:

```bash
ROOSTOO_API_KEY=your_api_key_here
ROOSTOO_API_SECRET=your_api_secret_here
ROOSTOO_BASE_URL=your_mock_exchange_url_here
```

If Binance or other external endpoints also require configuration, add them here as well.

### Important notes
- never commit your real `.env` file
- only commit `.env.example`
- keep all secrets outside source code

---

## 9. Running the Project

### Run the live mock trading bot
```bash
python main.py
```

### Run the backtest
```bash
python backtest.py
```

### Expected live behaviour
When running live, the bot should:
- fetch market data for each configured symbol
- compute indicators and latest signal
- determine whether to enter, top up, hold, or exit
- send mock orders to Roostoo when conditions are satisfied
- persist runtime state
- write logs for observability

---

## 10. Backtesting Approach

The backtest uses the **same strategy logic** as the live system wherever possible.

This is important because it reduces mismatch between:
- live decision rules
- historical simulation rules

### Backtest outputs typically include
- total return
- trade count
- win rate
- drawdown metrics
- per-trade logs
- portfolio equity curve

### Why this matters
A clean submission should demonstrate that:
- the strategy is logically coherent
- backtest and live logic are aligned
- risk management is explicit rather than implied

---

## 11. Logging and State Persistence

### Bot log
Runtime activity is written to:

```bash
bot/logs/bot.log
```

Typical log contents:
- data refresh status
- signal state by symbol
- order submission attempts
- successful fills
- exit / stop-loss events
- error messages and retry context

### Trade log
Trade records are written to:

```bash
bot/logs/trades.csv
```

Typical columns include:
- timestamp
- symbol
- side
- price
- quantity
- order_id
- api_response
- pnl
- signal_reason
- strategy_state

### Runtime state
Open-position context is persisted so the bot can recover cleanly after restart.

This helps prevent:
- duplicate entries on restart
- loss of stop-loss reference price
- inconsistent position tracking across sessions

---

## 12. Assumptions and Limitations

### Assumptions
- rolling VWAP is a reasonable short-term fair-value anchor
- stretched downside moves can mean-revert
- closed-candle execution is sufficient for the intended frequency
- mock execution is an acceptable approximation for hackathon testing

### Limitations
- live fills may differ from backtest assumptions
- slippage and latency may affect real-world performance
- mean reversion strategies can underperform during strong directional breakdowns
- parameter sensitivity may vary across volatility regimes
- performance depends on data quality and exchange uptime

---

## 13. Future Improvements

Possible next improvements include:
- volatility-adjusted allocation sizing
- cooldown logic after stop-loss exits
- per-symbol performance analytics
- transaction cost and slippage modelling in backtests
- regime filters beyond simple trend SMA
- automated health checks and reconnect logic

---

