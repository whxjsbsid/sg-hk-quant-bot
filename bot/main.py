import time
from dotenv import load_dotenv

load_dotenv()

print("bot.main started")

from bot.execution.roostoo_client import RoostooClient
from bot.logs.trade_logger import TradeLogger
from bot.logs.activity_logger import setup_activity_logger
from bot.data.binance_loader import load_binance_klines
from bot.strategy.vwap_reversion import generate_vwap_signal
from bot.config import settings


client = RoostooClient()
trade_logger = TradeLogger()
activity_logger = setup_activity_logger()

LAST_PROCESSED_CANDLE = None
CURRENT_POSITION = None  # 0 = flat, 1 = long


def parse_pair(pair: str) -> tuple[str, str]:
    if "/" in pair:
        base_coin, quote_coin = pair.split("/", 1)
        return base_coin.strip().upper(), quote_coin.strip().upper()
    return "BTC", "USD"


def log_balances(base_coin: str, quote_coin: str, prefix: str = "") -> dict:
    try:
        full_balance = client.get_balance()
        free_base = client.get_free_balance(base_coin)
        free_quote = client.get_free_balance(quote_coin)
        free_usdt = client.get_free_balance("USDT")

        if prefix:
            print(prefix)
            activity_logger.info(prefix)

        print("Full balance:")
        print(full_balance)
        print(f"Free {base_coin} balance:", free_base)
        print(f"Free {quote_coin} balance:", free_quote)
        print("Free USDT balance:", free_usdt)

        activity_logger.info(f"Full balance: {full_balance}")
        activity_logger.info(f"Free {base_coin} balance: {free_base}")
        activity_logger.info(f"Free {quote_coin} balance: {free_quote}")
        activity_logger.info(f"Free USDT balance: {free_usdt}")

        return {
            "full_balance": full_balance,
            "free_base": free_base,
            "free_quote": free_quote,
            "free_usdt": free_usdt,
        }
    except Exception as e:
        print("Failed to fetch balances:", e)
        activity_logger.exception("Failed to fetch balances")
        return {
            "full_balance": None,
            "free_base": 0.0,
            "free_quote": 0.0,
            "free_usdt": 0.0,
        }


def infer_position(qty: float, base_coin: str, quote_coin: str) -> int:
    balances = log_balances(base_coin, quote_coin, prefix="Checking balances for initial position...")
    free_base = balances["free_base"]
    return 1 if free_base >= qty else 0


def run_once():
    global LAST_PROCESSED_CANDLE, CURRENT_POSITION

    print("Entered run_once")

    symbol = getattr(settings, "BINANCE_SYMBOL", "BTCUSDT")
    pair = getattr(settings, "ROOSTOO_PAIR", "BTC/USD")
    interval = getattr(settings, "INTERVAL", "15m")
    limit = getattr(settings, "LIMIT", 3000)
    vwap_window = getattr(settings, "VWAP_WINDOW", 20)
    lower_std_mult = getattr(settings, "LOWER_STD_MULT", 0.75)
    strong_exit_std_mult = getattr(settings, "STRONG_EXIT_STD_MULT", 2.0)
    trend_window = getattr(settings, "TREND_WINDOW", 100)
    qty = getattr(settings, "QTY", 0.01)

    base_coin, quote_coin = parse_pair(pair)

    try:
        if CURRENT_POSITION is None:
            CURRENT_POSITION = infer_position(qty, base_coin, quote_coin)
            print("Initial CURRENT_POSITION =", CURRENT_POSITION)
            activity_logger.info(f"Initial CURRENT_POSITION = {CURRENT_POSITION}")

        print("Loading Binance data...")
        activity_logger.info(
            f"Loading Binance data for symbol={symbol}, interval={interval}, limit={limit}"
        )
        df = load_binance_klines(symbol=symbol, interval=interval, limit=limit)

        print("Generating signal...")
        activity_logger.info(
            f"Generating VWAP signal with window={vwap_window}, "
            f"lower_std_mult={lower_std_mult}, "
            f"strong_exit_std_mult={strong_exit_std_mult}, "
            f"trend_window={trend_window}"
        )
        df = generate_vwap_signal(
            df,
            window=vwap_window,
            lower_std_mult=lower_std_mult,
            strong_exit_std_mult=strong_exit_std_mult,
            trend_window=trend_window,
        )

        print("Rows in df:", len(df))

        if len(df) < 3:
            msg = "Not enough rows to evaluate closed-candle signal."
            print(msg)
            activity_logger.info(msg)
            return

        required_cols = [
            "close",
            "vwap",
            "lower_band",
            "strong_upper_band",
            "signal",
            "close_time",
        ]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            msg = f"Missing required columns: {missing_cols}"
            print(msg)
            activity_logger.info(msg)
            return

        if df[required_cols].tail(3).isnull().any().any():
            msg = "Latest rows contain NaN values. Skipping run."
            print(msg)
            activity_logger.info(msg)
            return

        print("\nLatest rows:")
        print(df[required_cols].tail(5))

        prev_row = df.iloc[-3]
        latest_row = df.iloc[-2]

        candle_time = str(latest_row["close_time"])
        print("\nLatest closed candle_time =", candle_time)

        if LAST_PROCESSED_CANDLE == candle_time:
            msg = f"Closed candle {candle_time} already processed. Skipping."
            print(msg)
            activity_logger.info(msg)
            return

        prev_signal = int(prev_row["signal"])
        latest_signal = int(latest_row["signal"])

        print("prev_signal =", prev_signal)
        print("latest_signal =", latest_signal)
        print("CURRENT_POSITION =", CURRENT_POSITION)

        if prev_signal not in (0, 1) or latest_signal not in (0, 1):
            msg = (
                "Unexpected signal values detected. "
                "This main.py assumes long-only signals: 0 = flat, 1 = long."
            )
            print(msg)
            activity_logger.info(msg)
            LAST_PROCESSED_CANDLE = candle_time
            return

        side = None
        signal_reason = None

        if CURRENT_POSITION == 0 and prev_signal == 0 and latest_signal == 1:
            balances = log_balances(base_coin, quote_coin, prefix="Checking balances before BUY...")
            if balances["free_quote"] <= 0 and balances["free_usdt"] <= 0:
                msg = f"Skip BUY: no available {quote_coin} or USDT balance."
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                return

            side = "BUY"
            signal_reason = "Signal flipped from 0 to 1 on latest closed candle"

        elif CURRENT_POSITION == 1 and prev_signal == 1 and latest_signal == 0:
            balances = log_balances(base_coin, quote_coin, prefix="Checking balances before SELL...")
            free_base = balances["free_base"]

            if free_base < qty:
                msg = f"Skip SELL: only {free_base} {base_coin} available, need {qty}"
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                return

            side = "SELL"
            signal_reason = "Signal flipped from 1 to 0 on latest closed candle"

        if side is None:
            msg = (
                f"No trade signal on candle {candle_time}. "
                f"prev_signal={prev_signal}, latest_signal={latest_signal}, "
                f"CURRENT_POSITION={CURRENT_POSITION}"
            )
            print(msg)
            activity_logger.info(msg)
            LAST_PROCESSED_CANDLE = candle_time
            return

        print(f"\nPlacing {side} order...")
        activity_logger.info(
            f"Placing {side} order for pair={pair}, quantity={qty}, reason={signal_reason}"
        )

        order_response = client.place_order(
            pair=pair,
            side=side,
            quantity=qty,
            order_type="MARKET",
        )

        print("Order response:")
        print(order_response)

        order_id = order_response.get("OrderDetail", {}).get("OrderID", "")

        if order_id:
            print("\nOrder query by ID:")
            print(client.query_order(order_id=order_id))
        else:
            print("\nOrder ID not found in response. Falling back to pair query:")
            print(client.query_order(pair=pair, limit=5))

        log_balances(base_coin, quote_coin, prefix="Balances after order:")

        trade_logger.log_trade(
            symbol=symbol,
            side=side,
            price=float(latest_row["close"]),
            quantity=qty,
            order_id=str(order_id),
            api_response=order_response,
            pnl=None,
            signal_reason=signal_reason,
            strategy_state={
                "pair": pair,
                "interval": interval,
                "candle_time": candle_time,
                "prev_signal": prev_signal,
                "latest_signal": latest_signal,
                "current_position_before_trade": CURRENT_POSITION,
                "vwap": float(latest_row["vwap"]),
                "lower_band": float(latest_row["lower_band"]),
                "strong_upper_band": float(latest_row["strong_upper_band"]),
            },
        )

        activity_logger.info(
            f"Placed {side} order for {qty} {pair}. "
            f"order_id={order_id}, reason={signal_reason}"
        )

        if side == "BUY":
            CURRENT_POSITION = 1
        elif side == "SELL":
            CURRENT_POSITION = 0

        LAST_PROCESSED_CANDLE = candle_time
        print("Updated CURRENT_POSITION =", CURRENT_POSITION)
        activity_logger.info(
            f"Updated CURRENT_POSITION = {CURRENT_POSITION}; "
            f"LAST_PROCESSED_CANDLE = {LAST_PROCESSED_CANDLE}"
        )

    except Exception as e:
        print("run_once failed:", e)
        activity_logger.exception("run_once failed")


if __name__ == "__main__":
    print("Starting bot...")
    activity_logger.info("Bot started")

    poll_seconds = getattr(settings, "POLL_SECONDS", 60)

    while True:
        run_once()
        print(f"Sleeping for {poll_seconds} seconds...\n")
        activity_logger.info(f"Sleeping for {poll_seconds} seconds")
        time.sleep(poll_seconds)
