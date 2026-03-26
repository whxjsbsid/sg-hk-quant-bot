# bot/config/settings.py
"""
Central configuration for the trading bot.

This module keeps all strategy, execution, portfolio, and runtime parameters
in one place so both live trading and backtesting use the same settings.
"""

from __future__ import annotations

# ============================================================================
# Portfolio / Market Configuration
# ============================================================================

# Each market defines:
# - binance_symbol: symbol used for Binance candle data
# - roostoo_pair: pair used for mock order execution on Roostoo
# - base_coin / quote_coin: asset naming used across logs and execution
# - target_alloc_pct: target fraction of portfolio capital allocated to the coin
MARKETS = [
    {
        "binance_symbol": "BTCUSDT",
        "roostoo_pair": "BTC/USD",
        "base_coin": "BTC",
        "quote_coin": "USD",
        "target_alloc_pct": 0.30,
    },
    {
        "binance_symbol": "ETHUSDT",
        "roostoo_pair": "ETH/USD",
        "base_coin": "ETH",
        "quote_coin": "USD",
        "target_alloc_pct": 0.30,
    },
    {
        "binance_symbol": "SOLUSDT",
        "roostoo_pair": "SOL/USD",
        "base_coin": "SOL",
        "quote_coin": "USD",
        "target_alloc_pct": 0.30,
    },
]

# Optional portfolio-level validation.
TOTAL_TARGET_ALLOCATION = sum(market["target_alloc_pct"] for market in MARKETS)
MAX_TOTAL_TARGET_ALLOCATION = 1.00

# ============================================================================
# Market Data / Runtime Polling
# ============================================================================

# Candle interval used to generate signals.
INTERVAL = "15m"

# Number of historical candles loaded for indicator calculation / backtesting.
LIMIT = 3000

# Polling interval for live execution loop (in seconds).
POLL_SECONDS = 60

# ============================================================================
# Strategy Parameters: VWAP Mean Reversion
# ============================================================================

# Rolling window for VWAP and volatility calculations.
VWAP_WINDOW = 20

# Entry threshold:
# enter long when price is sufficiently below VWAP relative to rolling std dev.
LOWER_STD_MULT = 1.5

# Standard exit threshold:
# exit when price reverts closer to VWAP.
EXIT_STD_MULT = 1.25

# Strong exit threshold:
# can be used to force a more decisive exit when reversion is strong.
STRONG_EXIT_STD_MULT = 2.75

# Trend confirmation window used by the strategy.
TREND_WINDOW = 48

# ============================================================================
# Backtest / Portfolio Capital
# ============================================================================

# Starting cash balance used by the backtest.
INITIAL_CASH = 50_000

# ============================================================================
# Execution / Position Sizing
# ============================================================================

# Minimum trade quantity allowed by the bot.
MIN_QTY = 0.001

# Number of decimal places used when rounding order quantity.
QTY_DECIMALS = 4

# Slight reduction factor to avoid overselling due to rounding / precision.
SELL_BUFFER_RATIO = 0.9999

# If current position value falls sufficiently below target allocation,
# the bot may top up if a valid signal still exists.
TOP_UP_THRESHOLD_RATIO = 0.95

# If position size remains above this ratio of target allocation,
# the bot continues treating it as an active holding.
HOLDING_THRESHOLD_RATIO = 0.80

# Whether to fully liquidate the position when an exit signal occurs.
CLOSE_FULL_POSITION_ON_EXIT = True

# ============================================================================
# Risk Management
# ============================================================================

# Maximum tolerated loss from entry price before stop-loss exit is triggered.
STOP_LOSS_PCT = 0.05

# ============================================================================
# Runtime State / Persistence
# ============================================================================

# File used to persist live runtime state between loop iterations / restarts.
RUNTIME_STATE_FILE = "bot/runtime_state.json"
