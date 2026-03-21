import time
from typing import Optional
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

HOLDING_THRESHOLD_RATIO = 0.80
BUY_BUFFER_RATIO = 1.01


def parse_pair(pair: str) -> tuple[str, str]:
    if "/" in pair:
        base_coin, quote_coin = pair.split("/", 1)
        return base_coin.strip().upper(), quote_coin.strip().upper()
    return "BTC", "USD"


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def find_first_value(obj, key_names: set[str]):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in key_names and value not in (None, ""):
                return value
        for value in obj.values():
            found = find_first_value(value, key_names)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_first_value(item, key_names)
            if found not in (None, ""):
                return found
    return None


def extract_order_id(obj) -> str:
    value = find_first_value(
        obj,
        {
            "orderid",
            "order_id",
            "id",
        },
    )
    return str(value) if value not in (None, "") else ""


def extract_order_status(obj) -> str:
    value = find_first_value(
        obj,
        {
            "status",
            "orderstatus",
            "state",
            "order_state",
        },
    )
    return str(value).strip().upper() if value not in (None, "") else ""


def extract_fill_price(*objs, fallback: Optional[float] = None) -> Optional[float]:
    price_keys = {
        "avgprice",
        "averageprice",
        "avg_fill_price",
        "fillprice",
        "filledprice",
        "executedprice",
        "price",
    }
    for obj in objs:
        value = find_first_value(obj, price_keys)
        price = safe_float(value, default=0.0)
        if price > 0:
            return price
    return fallback


def has_explicit_failure(obj) -> bool:
    if obj is None:
        return False

    status = extract_order_status(obj)
    failure_statuses = {
        "REJECTED",
        "FAILED",
        "CANCELLED",
        "EXPIRED",
        "ERROR",
        "INVALID",
    }
    if status in failure_statuses:
        return True

    message_value = find_first_value(
        obj,
        {
            "message",
            "msg",
            "error",
            "errormsg",
            "error_message",
            "detail",
        },
    )
    if message_value not in (None, ""):
        message = str(message_value).lower()
        failure_words = [
            "reject",
            "failed",
            "error",
            "insufficient",
            "invalid",
            "not enough",
            "denied",
            "cancel",
            "expired",
        ]
        if any(word in message for word in failure_words):
            return True

    success_value = find_first_value(obj, {"success", "ok"})
    if isinstance(success_value, bool) and success_value is False:
        return True

    return False


def has_explicit_success(obj) -> bool:
    if obj is None:
        return False

    status = extract_order_status(obj)
    success_statuses = {
        "FILLED",
        "EXECUTED",
        "COMPLETED",
        "DONE",
        "SUCCESS",
        "CLOSED",
        "OPEN",
        "NEW",
        "PARTIALLY_FILLED",
        "PARTIAL",
    }
    if status in success_statuses:
        return True

    success_value = find_first_value(obj, {"success", "ok"})
    if isinstance(success_value, bool) and success_value is True:
        return True

    if extract_order_id(obj):
        return True

    return False


def log_balances(
    base_coin: str,
    quote_coin: str,
    prefix: str = "",
    force_refresh: bool = False,
) -> dict:
    try:
        full_balance = client.get_balance(force_refresh=force_refresh)
        free_base = safe_float(client.get_free_balance(base_coin, balance_snapshot=full_balance))
        free_quote = safe_float(client.get_free_balance(quote_coin, balance_snapshot=full_balance))
        free_usd = safe_float(client.get_free_balance("USD", balance_snapshot=full_balance))
        free_usdt = safe_float(client.get_free_balance("USDT", balance_snapshot=full_balance))

        if prefix:
            print(prefix)
            activity_logger.info(prefix)

        print("Full balance:")
        print(full_balance)
        print(f"Free {base_coin} balance:", free_base)
        print(f"Free {quote_coin} balance:", free_quote)
        print("Free USD balance:", free_usd)
        print("Free USDT balance:", free_usdt)

        activity_logger.info(f"Full balance: {full_balance}")
        activity_logger.info(f"Free {base_coin} balance: {free_base}")
        activity_logger.info(f"Free {quote_coin} balance: {free_quote}")
        activity_logger.info(f"Free USD balance: {free_usd}")
        activity_logger.info(f"Free USDT balance: {free_usdt}")

        return {
            "full_balance": full_balance,
            "free_base": free_base,
            "free_quote": free_quote,
            "free_usd": free_usd,
            "free_usdt": free_usdt,
        }
    except Exception as e:
        print("Failed to fetch balances:", e)
        activity_logger.exception("Failed to fetch balances")
        return {
            "full_balance": None,
            "free_base": 0.0,
            "free_quote": 0.0,
            "free_usd": 0.0,
            "free_usdt": 0.0,
        }


def get_available_quote_balance(quote_coin: str, balances: dict) -> float:
    free_quote = safe_float(balances.get("free_quote"), 0.0)
    free_usd = safe_float(balances.get("free_usd"), 0.0)
    free_usdt = safe_float(balances.get("free_usdt"), 0.0)

    if quote_coin == "USD":
        return max(free_quote, free_usd) + free_usdt

    if quote_coin == "USDT":
        return max(free_quote, free_usdt)

    return free_quote


def infer_position_from_base_balance(free_base: float, qty: float) -> int:
    threshold = max(qty * HOLDING_THRESHOLD_RATIO, 1e-12)
    return 1 if free_base >= threshold else 0


def infer_position(qty: float, base_coin: str, quote_coin: str) -> int:
    balances = log_balances(
        base_coin,
        quote_coin,
        prefix="Checking balances for initial position...",
        force_refresh=True,
    )
    return infer_position_from_base_balance(balances["free_base"], qty)


def query_order_safely(pair: str, order_id: str = ""):
    try:
        if order_id:
            result = client.query_order(order_id=order_id)
            print("\nOrder query by ID:")
            print(result)
            return result

        result = client.query_order(pair=pair, limit=5)
        print("\nOrder ID not found in response. Falling back to pair query:")
        print(result)
        return result
    except Exception as e:
        print("Order query failed:", e)
        activity_logger.exception("Order query failed")
        return None


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
    qty = safe_float(getattr(settings, "QTY", 0.01), 0.01)

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

        latest_close = safe_float(latest_row["close"], 0.0)
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
            balances = log_balances(
                base_coin,
                quote_coin,
                prefix="Checking balances before BUY...",
                force_refresh=True,
            )
            available_quote = get_available_quote_balance(quote_coin, balances)
            estimated_cost = qty * latest_close * BUY_BUFFER_RATIO

            print("Estimated BUY cost:", estimated_cost)
            print("Available quote balance:", available_quote)

            activity_logger.info(
                f"BUY balance check: estimated_cost={estimated_cost}, available_quote={available_quote}"
            )

            if latest_close <= 0:
                msg = "Skip BUY: invalid latest close price."
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                return

            if available_quote < estimated_cost:
                msg = (
                    f"Skip BUY: available quote balance {available_quote} is below "
                    f"estimated cost {estimated_cost}"
                )
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                return

            side = "BUY"
            signal_reason = "Signal flipped from 0 to 1 on latest closed candle"

        elif CURRENT_POSITION == 1 and prev_signal == 1 and latest_signal == 0:
            balances = log_balances(
                base_coin,
                quote_coin,
                prefix="Checking balances before SELL...",
                force_refresh=True,
            )
            free_base = balances["free_base"]

            if free_base < qty * HOLDING_THRESHOLD_RATIO:
                msg = f"Skip SELL: only {free_base} {base_coin} available, need about {qty}"
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

        position_before_trade = CURRENT_POSITION

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

        order_id = extract_order_id(order_response)
        order_query = query_order_safely(pair=pair, order_id=order_id)

        post_trade_balances = log_balances(
            base_coin,
            quote_coin,
            prefix="Balances after order:",
            force_refresh=True,
        )
        position_after_trade = infer_position_from_base_balance(post_trade_balances["free_base"], qty)

        explicit_failure = has_explicit_failure(order_response) or has_explicit_failure(order_query)
        explicit_success = (
            has_explicit_success(order_response)
            or has_explicit_success(order_query)
            or bool(order_id)
        )

        expected_position = 1 if side == "BUY" else 0
        balance_confirms_trade = position_after_trade == expected_position

        order_success = False
        if balance_confirms_trade:
            order_success = True
        elif explicit_success and not explicit_failure:
            order_success = True

        actual_trade_price = extract_fill_price(
            order_query,
            order_response,
            fallback=latest_close if latest_close > 0 else None,
        )

        CURRENT_POSITION = position_after_trade
        LAST_PROCESSED_CANDLE = candle_time

        if order_success:
            trade_logger.log_trade(
                symbol=symbol,
                side=side,
                price=actual_trade_price if actual_trade_price is not None else latest_close,
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
                    "current_position_before_trade": position_before_trade,
                    "current_position_after_trade": CURRENT_POSITION,
                    "vwap": float(latest_row["vwap"]),
                    "lower_band": float(latest_row["lower_band"]),
                    "strong_upper_band": float(latest_row["strong_upper_band"]),
                },
            )

            activity_logger.info(
                f"Placed {side} order for {qty} {pair}. "
                f"order_id={order_id}, fill_price={actual_trade_price}, "
                f"reason={signal_reason}, "
                f"CURRENT_POSITION={CURRENT_POSITION}, "
                f"LAST_PROCESSED_CANDLE={LAST_PROCESSED_CANDLE}"
            )

            print("Updated CURRENT_POSITION =", CURRENT_POSITION)
        else:
            msg = (
                f"Order may not have succeeded cleanly. "
                f"side={side}, order_id={order_id}, "
                f"explicit_failure={explicit_failure}, explicit_success={explicit_success}, "
                f"position_before_trade={position_before_trade}, "
                f"position_after_trade={CURRENT_POSITION}"
            )
            print(msg)
            activity_logger.warning(msg)

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
