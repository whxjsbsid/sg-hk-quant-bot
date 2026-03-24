import inspect
import json
import math
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

print("bot.main started")

from bot.config import settings
from bot.data.binance_loader import load_binance_klines
from bot.execution.roostoo_client import RoostooClient
from bot.logs.activity_logger import setup_activity_logger
from bot.logs.trade_logger import TradeLogger
from bot.strategy.vwap_reversion import generate_vwap_signal


client = RoostooClient()
trade_logger = TradeLogger()
activity_logger = setup_activity_logger()

LAST_PROCESSED_CANDLE = None
CURRENT_POSITION = None  # 0 = flat, 1 = long
CURRENT_ENTRY_PRICE = None
CURRENT_STOP_LOSS_PRICE = None


def get_setting(name: str, default=None):
    return getattr(settings, name, default)


def get_str_setting(name: str, default: str) -> str:
    value = get_setting(name, default)
    if value is None:
        return default
    return str(value)


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def get_float_setting(name: str, default: float) -> float:
    return safe_float(get_setting(name, default), default)


def get_int_setting(name: str, default: int) -> int:
    value = get_setting(name, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_bool_setting(name: str, default: bool) -> bool:
    value = get_setting(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


def get_state_file() -> Path:
    return Path(get_str_setting("RUNTIME_STATE_FILE", "bot/runtime_state.json"))


def parse_pair(pair: str) -> tuple:
    if "/" in pair:
        base_coin, quote_coin = pair.split("/", 1)
        return base_coin.strip().upper(), quote_coin.strip().upper()

    base_coin = get_str_setting("BASE_COIN", "BTC").strip().upper()
    quote_coin = get_str_setting("QUOTE_COIN", "USD").strip().upper()
    return base_coin, quote_coin


def get_min_qty() -> float:
    return get_float_setting("MIN_QTY", 0.001)


def get_qty_decimals() -> int:
    return get_int_setting("QTY_DECIMALS", 4)


def get_target_alloc_pct() -> float:
    return get_float_setting("TARGET_ALLOC_PCT", 0.20)


def get_sell_buffer_ratio() -> float:
    return get_float_setting("SELL_BUFFER_RATIO", 0.999)


def get_close_full_position_on_exit() -> bool:
    return get_bool_setting("CLOSE_FULL_POSITION_ON_EXIT", True)


def get_stop_loss_pct() -> float:
    return max(get_float_setting("STOP_LOSS_PCT", 0.03), 0.0)


def get_top_up_threshold_ratio() -> float:
    ratio = get_float_setting("TOP_UP_THRESHOLD_RATIO", 0.95)
    return min(max(ratio, 0.0), 1.0)


def get_holding_threshold_ratio() -> float:
    return max(get_float_setting("HOLDING_THRESHOLD_RATIO", 0.80), 0.0)


def save_runtime_state() -> None:
    state = {
        "last_processed_candle": LAST_PROCESSED_CANDLE,
        "current_position": CURRENT_POSITION,
        "current_entry_price": CURRENT_ENTRY_PRICE,
        "current_stop_loss_price": CURRENT_STOP_LOSS_PRICE,
    }

    state_file = get_state_file()

    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as e:
        print("Failed to save runtime state:", e)
        activity_logger.exception("Failed to save runtime state")


def load_runtime_state() -> None:
    global LAST_PROCESSED_CANDLE, CURRENT_POSITION
    global CURRENT_ENTRY_PRICE, CURRENT_STOP_LOSS_PRICE

    state_file = get_state_file()
    if not state_file.exists():
        return

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        LAST_PROCESSED_CANDLE = state.get("last_processed_candle")
        CURRENT_POSITION = state.get("current_position")
        CURRENT_ENTRY_PRICE = safe_float(state.get("current_entry_price"), default=0.0)
        CURRENT_STOP_LOSS_PRICE = safe_float(
            state.get("current_stop_loss_price"), default=0.0
        )

        if CURRENT_ENTRY_PRICE <= 0:
            CURRENT_ENTRY_PRICE = None
        if CURRENT_STOP_LOSS_PRICE <= 0:
            CURRENT_STOP_LOSS_PRICE = None

        print("Loaded runtime state:", state)
        activity_logger.info("Loaded runtime state: {0}".format(state))

    except Exception as e:
        print("Failed to load runtime state:", e)
        activity_logger.exception("Failed to load runtime state")


def round_down(value: float, decimals: int) -> float:
    if decimals < 0:
        decimals = 0
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


def find_first_value(obj, key_names: set):
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
        free_base = safe_float(
            client.get_free_balance(base_coin, balance_snapshot=full_balance)
        )
        free_quote = safe_float(
            client.get_free_balance(quote_coin, balance_snapshot=full_balance)
        )
        free_usd = safe_float(
            client.get_free_balance("USD", balance_snapshot=full_balance)
        )
        free_usdt = safe_float(
            client.get_free_balance("USDT", balance_snapshot=full_balance)
        )

        if prefix:
            print(prefix)
            activity_logger.info(prefix)

        print("Full balance:")
        print(full_balance)
        print("Free {0} balance: {1}".format(base_coin, free_base))
        print("Free {0} balance: {1}".format(quote_coin, free_quote))
        print("Free USD balance:", free_usd)
        print("Free USDT balance:", free_usdt)

        activity_logger.info("Full balance: {0}".format(full_balance))
        activity_logger.info("Free {0} balance: {1}".format(base_coin, free_base))
        activity_logger.info("Free {0} balance: {1}".format(quote_coin, free_quote))
        activity_logger.info("Free USD balance: {0}".format(free_usd))
        activity_logger.info("Free USDT balance: {0}".format(free_usdt))

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


def require_balance_snapshot(balances: dict, context: str) -> None:
    if balances.get("full_balance") is None:
        raise RuntimeError(
            "Failed to fetch balance during {0}. Check Roostoo API auth before running the bot.".format(context)
        )


def get_available_quote_balance(quote_coin: str, balances: dict) -> float:
    free_quote = safe_float(balances.get("free_quote"), 0.0)
    free_usd = safe_float(balances.get("free_usd"), 0.0)
    free_usdt = safe_float(balances.get("free_usdt"), 0.0)

    if quote_coin == "USD":
        return max(free_quote, free_usd) + free_usdt

    if quote_coin == "USDT":
        return max(free_quote, free_usdt)

    return free_quote


def get_total_equity(latest_price: float, balances: dict, quote_coin: str) -> float:
    quote_value = get_available_quote_balance(quote_coin, balances)
    base_value = safe_float(balances.get("free_base"), 0.0) * latest_price
    return quote_value + base_value


def compute_entry_qty(latest_price: float, balances: dict, quote_coin: str) -> float:
    target_alloc_pct = get_target_alloc_pct()
    min_qty = get_min_qty()
    qty_decimals = get_qty_decimals()

    if latest_price <= 0:
        return 0.0

    total_equity = get_total_equity(latest_price, balances, quote_coin)
    target_notional = total_equity * target_alloc_pct
    raw_qty = target_notional / latest_price
    qty = round_down(raw_qty, qty_decimals)

    if qty < min_qty:
        return 0.0

    return qty


def compute_top_up_qty(latest_price: float, balances: dict, quote_coin: str):
    min_qty = get_min_qty()
    qty_decimals = get_qty_decimals()

    current_base = safe_float(balances.get("free_base"), 0.0)
    target_qty = compute_entry_qty(latest_price, balances, quote_coin)

    if target_qty <= 0:
        return 0.0, target_qty, current_base

    gap_qty = round_down(max(target_qty - current_base, 0.0), qty_decimals)

    if gap_qty < min_qty:
        return 0.0, target_qty, current_base

    return gap_qty, target_qty, current_base


def compute_exit_qty(balances: dict) -> float:
    min_qty = get_min_qty()
    qty_decimals = get_qty_decimals()
    sell_buffer_ratio = get_sell_buffer_ratio()
    close_full_position_on_exit = get_close_full_position_on_exit()

    free_base = safe_float(balances.get("free_base"), 0.0)

    if close_full_position_on_exit:
        qty = round_down(free_base, qty_decimals)
    else:
        raw_qty = free_base * sell_buffer_ratio
        qty = round_down(raw_qty, qty_decimals)

    if qty < min_qty:
        return 0.0

    return qty


def infer_position_from_base_balance(free_base: float) -> int:
    threshold = max(get_min_qty() * get_holding_threshold_ratio(), 1e-12)
    return 1 if free_base >= threshold else 0


def infer_position(base_coin: str, quote_coin: str) -> int:
    balances = log_balances(
        base_coin,
        quote_coin,
        prefix="Checking balances for initial position...",
        force_refresh=True,
    )
    require_balance_snapshot(balances, "initial position check")
    return infer_position_from_base_balance(balances["free_base"])


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


def build_signal_kwargs() -> dict:
    setting_map = {
        "window": "VWAP_WINDOW",
        "lower_std_mult": "LOWER_STD_MULT",
        "exit_std_mult": "EXIT_STD_MULT",
        "strong_exit_std_mult": "STRONG_EXIT_STD_MULT",
        "trend_window": "TREND_WINDOW",
    }

    signature = inspect.signature(generate_vwap_signal)
    kwargs = {}

    for arg_name, setting_name in setting_map.items():
        if arg_name not in signature.parameters:
            continue

        param = signature.parameters[arg_name]
        default = None if param.default is inspect._empty else param.default
        value = get_setting(setting_name, default)
        if value is not None:
            kwargs[arg_name] = value

    return kwargs


def run_once():
    global LAST_PROCESSED_CANDLE, CURRENT_POSITION
    global CURRENT_ENTRY_PRICE, CURRENT_STOP_LOSS_PRICE

    print("Entered run_once")

    symbol = get_str_setting("BINANCE_SYMBOL", "BTCUSDT")
    pair = get_str_setting("ROOSTOO_PAIR", "BTC/USD")
    interval = get_str_setting("INTERVAL", "15m")
    limit = get_int_setting("LIMIT", 3000)
    stop_loss_pct = get_stop_loss_pct()
    top_up_threshold_ratio = get_top_up_threshold_ratio()

    signal_kwargs = build_signal_kwargs()

    base_coin, quote_coin = parse_pair(pair)

    try:
        if CURRENT_POSITION is None:
            CURRENT_POSITION = infer_position(base_coin, quote_coin)
            print("Initial CURRENT_POSITION =", CURRENT_POSITION)
            activity_logger.info(
                "Initial CURRENT_POSITION = {0}".format(CURRENT_POSITION)
            )

        print("Loading Binance data...")
        activity_logger.info(
            "Loading Binance data for symbol={0}, interval={1}, limit={2}".format(
                symbol, interval, limit
            )
        )
        df = load_binance_klines(symbol=symbol, interval=interval, limit=limit)

        print("Generating signal...")
        activity_logger.info(
            "Generating VWAP signal with kwargs={0}".format(signal_kwargs)
        )
        df = generate_vwap_signal(df, **signal_kwargs)

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
            msg = "Missing required columns: {0}".format(missing_cols)
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
            msg = "Closed candle {0} already processed. Skipping.".format(candle_time)
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
            save_runtime_state()
            return

        reconciliation_balances = log_balances(
            base_coin,
            quote_coin,
            prefix="Checking balances for state reconciliation...",
            force_refresh=True,
        )
        require_balance_snapshot(reconciliation_balances, "state reconciliation")

        live_base_qty = safe_float(reconciliation_balances.get("free_base"), 0.0)
        live_position = infer_position_from_base_balance(live_base_qty)

        if CURRENT_POSITION != live_position:
            msg = (
                "Reconciling CURRENT_POSITION from runtime state {0} to live balance position {1}. "
                "live_base_qty={2}".format(CURRENT_POSITION, live_position, live_base_qty)
            )
            print(msg)
            activity_logger.warning(msg)
            CURRENT_POSITION = live_position
            save_runtime_state()

        if CURRENT_POSITION == 1 and CURRENT_ENTRY_PRICE is None and latest_close > 0:
            CURRENT_ENTRY_PRICE = latest_close
            CURRENT_STOP_LOSS_PRICE = latest_close * (1 - stop_loss_pct)

            msg = (
                "Position detected but no saved entry price found. "
                "Bootstrapping stop loss from latest close. "
                "entry_price={0}, stop_loss={1}".format(
                    CURRENT_ENTRY_PRICE, CURRENT_STOP_LOSS_PRICE
                )
            )
            print(msg)
            activity_logger.warning(msg)
            save_runtime_state()

        side = None
        signal_reason = None
        trade_qty = 0.0
        buy_was_top_up = False
        pre_trade_base_qty = 0.0
        target_qty_before_trade = 0.0

        if (
            CURRENT_POSITION == 1
            and CURRENT_STOP_LOSS_PRICE is not None
            and latest_close > 0
            and latest_close <= CURRENT_STOP_LOSS_PRICE
        ):
            balances = log_balances(
                base_coin,
                quote_coin,
                prefix="Checking balances before STOP-LOSS SELL...",
                force_refresh=True,
            )
            require_balance_snapshot(balances, "STOP-LOSS SELL balance check")

            free_base = balances["free_base"]
            trade_qty = compute_exit_qty(balances)

            print("Computed STOP-LOSS SELL qty:", trade_qty)
            print("Free base balance:", free_base)
            print("Current entry price:", CURRENT_ENTRY_PRICE)
            print("Current stop loss price:", CURRENT_STOP_LOSS_PRICE)
            print("Latest close:", latest_close)

            activity_logger.info(
                "STOP-LOSS SELL sizing: order_qty={0}, free_base={1}, entry_price={2}, stop_loss_price={3}, latest_close={4}".format(
                    trade_qty,
                    free_base,
                    CURRENT_ENTRY_PRICE,
                    CURRENT_STOP_LOSS_PRICE,
                    latest_close,
                )
            )

            if trade_qty <= 0:
                msg = "Skip STOP-LOSS SELL: computed exit quantity is too small."
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                save_runtime_state()
                return

            side = "SELL"
            signal_reason = (
                "Stop loss hit: latest close {0} <= stop loss {1}".format(
                    latest_close, CURRENT_STOP_LOSS_PRICE
                )
            )

        elif CURRENT_POSITION == 0 and latest_signal == 1:
            balances = log_balances(
                base_coin,
                quote_coin,
                prefix="Checking balances before BUY...",
                force_refresh=True,
            )
            require_balance_snapshot(balances, "BUY balance check")

            if latest_close <= 0:
                msg = "Skip BUY: invalid latest close price."
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                save_runtime_state()
                return

            available_quote = get_available_quote_balance(quote_coin, balances)
            trade_qty = compute_entry_qty(latest_close, balances, quote_coin)
            target_qty_before_trade = trade_qty
            estimated_cost = trade_qty * latest_close

            print("Computed BUY qty:", trade_qty)
            print("Estimated BUY cost:", estimated_cost)
            print("Available quote balance:", available_quote)

            activity_logger.info(
                "BUY sizing: order_qty={0}, estimated_cost={1}, available_quote={2}".format(
                    trade_qty, estimated_cost, available_quote
                )
            )

            if trade_qty <= 0:
                msg = "Skip BUY: computed order quantity is too small."
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                save_runtime_state()
                return

            if available_quote < estimated_cost:
                msg = (
                    "Skip BUY: available quote balance {0} is below estimated cost {1}".format(
                        available_quote, estimated_cost
                    )
                )
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                save_runtime_state()
                return

            side = "BUY"
            if prev_signal == 0:
                signal_reason = "Signal flipped from 0 to 1 on latest closed candle"
            else:
                signal_reason = "Flat while signal is still 1, buying back to target allocation"

        elif CURRENT_POSITION == 1 and latest_signal == 1:
            balances = log_balances(
                base_coin,
                quote_coin,
                prefix="Checking balances before TOP-UP BUY...",
                force_refresh=True,
            )
            require_balance_snapshot(balances, "TOP-UP BUY balance check")

            if latest_close <= 0:
                msg = "Skip TOP-UP BUY: invalid latest close price."
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                save_runtime_state()
                return

            available_quote = get_available_quote_balance(quote_coin, balances)
            trade_qty, target_qty_before_trade, current_base = compute_top_up_qty(
                latest_close, balances, quote_coin
            )

            needs_top_up = (
                target_qty_before_trade > 0
                and current_base < target_qty_before_trade * top_up_threshold_ratio
            )
            estimated_cost = trade_qty * latest_close

            print("Current base qty:", current_base)
            print("Target qty:", target_qty_before_trade)
            print("Computed TOP-UP BUY qty:", trade_qty)
            print("Estimated TOP-UP BUY cost:", estimated_cost)
            print("Available quote balance:", available_quote)

            activity_logger.info(
                "TOP-UP BUY sizing: current_base={0}, target_qty={1}, top_up_qty={2}, estimated_cost={3}, available_quote={4}".format(
                    current_base,
                    target_qty_before_trade,
                    trade_qty,
                    estimated_cost,
                    available_quote,
                )
            )

            if not needs_top_up:
                msg = (
                    "No top-up needed. current_base={0}, target_qty={1}, threshold_ratio={2}".format(
                        current_base, target_qty_before_trade, top_up_threshold_ratio
                    )
                )
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                save_runtime_state()
                return

            if trade_qty <= 0:
                msg = "Skip TOP-UP BUY: computed top-up quantity is too small."
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                save_runtime_state()
                return

            if available_quote < estimated_cost:
                msg = (
                    "Skip TOP-UP BUY: available quote balance {0} is below estimated cost {1}".format(
                        available_quote, estimated_cost
                    )
                )
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                save_runtime_state()
                return

            side = "BUY"
            buy_was_top_up = True
            pre_trade_base_qty = current_base
            signal_reason = (
                "Top-up buy: current base {0} is below target qty {1}".format(
                    current_base, target_qty_before_trade
                )
            )

        elif CURRENT_POSITION == 1 and prev_signal == 1 and latest_signal == 0:
            balances = log_balances(
                base_coin,
                quote_coin,
                prefix="Checking balances before SELL...",
                force_refresh=True,
            )
            require_balance_snapshot(balances, "SELL balance check")

            free_base = balances["free_base"]
            trade_qty = compute_exit_qty(balances)

            print("Computed SELL qty:", trade_qty)
            print("Free base balance:", free_base)

            activity_logger.info(
                "SELL sizing: order_qty={0}, free_base={1}".format(
                    trade_qty, free_base
                )
            )

            if trade_qty <= 0:
                msg = "Skip SELL: computed exit quantity is too small."
                print(msg)
                activity_logger.info(msg)
                LAST_PROCESSED_CANDLE = candle_time
                save_runtime_state()
                return

            side = "SELL"
            signal_reason = "Signal flipped from 1 to 0 on latest closed candle"

        if side is None:
            msg = (
                "No trade signal on candle {0}. prev_signal={1}, latest_signal={2}, CURRENT_POSITION={3}".format(
                    candle_time, prev_signal, latest_signal, CURRENT_POSITION
                )
            )
            print(msg)
            activity_logger.info(msg)
            LAST_PROCESSED_CANDLE = candle_time
            save_runtime_state()
            return

        position_before_trade = CURRENT_POSITION
        entry_price_before_trade = CURRENT_ENTRY_PRICE
        stop_loss_price_before_trade = CURRENT_STOP_LOSS_PRICE

        print("\nPlacing {0} order...".format(side))
        activity_logger.info(
            "Placing {0} order for pair={1}, quantity={2}, reason={3}".format(
                side, pair, trade_qty, signal_reason
            )
        )

        order_response = client.place_order(
            pair=pair,
            side=side,
            quantity=trade_qty,
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
        require_balance_snapshot(post_trade_balances, "post-trade balance check")

        position_after_trade = infer_position_from_base_balance(
            post_trade_balances["free_base"]
        )

        explicit_failure = has_explicit_failure(order_response) or has_explicit_failure(
            order_query
        )
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
            fill_price_for_state = (
                actual_trade_price if actual_trade_price is not None else latest_close
            )

            if side == "BUY":
                if (
                    buy_was_top_up
                    and entry_price_before_trade is not None
                    and pre_trade_base_qty > 0
                    and trade_qty > 0
                ):
                    total_qty = pre_trade_base_qty + trade_qty
                    CURRENT_ENTRY_PRICE = (
                        (pre_trade_base_qty * entry_price_before_trade)
                        + (trade_qty * fill_price_for_state)
                    ) / total_qty
                else:
                    CURRENT_ENTRY_PRICE = fill_price_for_state

                CURRENT_STOP_LOSS_PRICE = CURRENT_ENTRY_PRICE * (1 - stop_loss_pct)
            else:
                CURRENT_ENTRY_PRICE = None
                CURRENT_STOP_LOSS_PRICE = None

            save_runtime_state()

            trade_logger.log_trade(
                symbol=symbol,
                side=side,
                price=actual_trade_price if actual_trade_price is not None else latest_close,
                quantity=trade_qty,
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
                    "trade_qty": trade_qty,
                    "buy_was_top_up": buy_was_top_up,
                    "pre_trade_base_qty": pre_trade_base_qty,
                    "target_qty_before_trade": target_qty_before_trade,
                    "entry_price_before_trade": entry_price_before_trade,
                    "stop_loss_price_before_trade": stop_loss_price_before_trade,
                    "entry_price_after_trade": CURRENT_ENTRY_PRICE,
                    "stop_loss_price_after_trade": CURRENT_STOP_LOSS_PRICE,
                    "stop_loss_pct": stop_loss_pct,
                    "top_up_threshold_ratio": top_up_threshold_ratio,
                    "holding_threshold_ratio": get_holding_threshold_ratio(),
                    "signal_kwargs": signal_kwargs,
                    "vwap": float(latest_row["vwap"]),
                    "lower_band": float(latest_row["lower_band"]),
                    "strong_upper_band": float(latest_row["strong_upper_band"]),
                },
            )

            activity_logger.info(
                "Placed {0} order for {1} {2}. order_id={3}, fill_price={4}, reason={5}, CURRENT_POSITION={6}, LAST_PROCESSED_CANDLE={7}".format(
                    side,
                    trade_qty,
                    pair,
                    order_id,
                    actual_trade_price,
                    signal_reason,
                    CURRENT_POSITION,
                    LAST_PROCESSED_CANDLE,
                )
            )

            print("Updated CURRENT_POSITION =", CURRENT_POSITION)
            print("Updated CURRENT_ENTRY_PRICE =", CURRENT_ENTRY_PRICE)
            print("Updated CURRENT_STOP_LOSS_PRICE =", CURRENT_STOP_LOSS_PRICE)
        else:
            save_runtime_state()
            msg = (
                "Order may not have succeeded cleanly. side={0}, order_id={1}, explicit_failure={2}, explicit_success={3}, position_before_trade={4}, position_after_trade={5}".format(
                    side,
                    order_id,
                    explicit_failure,
                    explicit_success,
                    position_before_trade,
                    CURRENT_POSITION,
                )
            )
            print(msg)
            activity_logger.warning(msg)

    except Exception as e:
        print("run_once failed:", e)
        activity_logger.exception("run_once failed")
        raise


if __name__ == "__main__":
    print("Starting bot...")
    activity_logger.info("Bot started")
    load_runtime_state()

    poll_seconds = get_int_setting("POLL_SECONDS", 60)

    while True:
        run_once()
        print("Sleeping for {0} seconds...\n".format(poll_seconds))
        activity_logger.info("Sleeping for {0} seconds".format(poll_seconds))
        time.sleep(poll_seconds)
