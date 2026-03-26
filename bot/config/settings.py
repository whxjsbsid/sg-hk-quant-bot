# bot/config/settings.py

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

TOTAL_TARGET_ALLOCATION = sum(market["target_alloc_pct"] for market in MARKETS)
MAX_TOTAL_TARGET_ALLOCATION = 1.00

INTERVAL = "15m"
LIMIT = 3000
POLL_SECONDS = 60

VWAP_WINDOW = 20
LOWER_STD_MULT = 1.5
EXIT_STD_MULT = 1.25
STRONG_EXIT_STD_MULT = 2.75
TREND_WINDOW = 48

INITIAL_CASH = 50_000

MIN_QTY = 0.001
QTY_DECIMALS = 4

SELL_BUFFER_RATIO = 0.9999
STOP_LOSS_PCT = 0.05
TOP_UP_THRESHOLD_RATIO = 0.95
HOLDING_THRESHOLD_RATIO = 0.80
CLOSE_FULL_POSITION_ON_EXIT = True

RUNTIME_STATE_FILE = "bot/runtime_state.json"
