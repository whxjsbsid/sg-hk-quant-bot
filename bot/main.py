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

RUNTIME_STATE = {}


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


def get_markets() -> list:
    markets = get_setting("MARKETS", [])
    if not isinstance(markets, list) or len(markets) == 0:
        raise ValueError("settings.MARKETS must be a non-empty list.")
    return markets


def normalize_market(market: dict) -> dict:
    pair = str(market["roostoo_pair"]).strip().upper()
    base_coin = str(market["base_coin"]).strip().upper()

    if "quote_coin" in market and market["quote_coin"] not in (None, ""):
        quote_coin = str(market["quote_coin"]).strip().upper()
    elif "/" in pair:
        _, quote_coin = pair.split("/", 1)
        quote_coin = quote_coin.strip().upper()
    else:
        quote_coin = "USD"

    return {
        "market_key": pair,
        "binance_symbol": str(market["binance_symbol"]).strip().upper(),
        "roostoo_pair": pair,
        "base_coin": base_coin,
        "quote_coin": quote_coin,
        "target_alloc_pct": max(safe_float(market.get("target_alloc_pct"), 0.0), 0.0),
    }


def get_min_qty() -> float:
    return get_float_setting("MIN_QTY", 0.001)


def get_qty_decimals() -> int:
    return get_int_setting("QTY_DECIMALS", 4)


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


def round_down(value: float, decimals: int) -> float:
    if decimals < 0:
        decimals = 0
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


def sanitize_market_state(state: dict) -> dict:
    current_position = state.get("current_position")
    if current_position not in (0, 1):
        current_position = None

    entry_price = safe_float(state.get("current_entry_price"), default=0.0)
    stop_loss_price = safe_float(state.get("current_stop_loss_price"), default=0.0)

    return {
        "last_processed_candle": state.get("last_processed_candle"),
        "current_position": current_position,
        "current_entry_price": entry_price if entry_price > 0 else None,
        "current_stop_loss_price": stop_loss_price if stop_loss_price > 0 else None,
    }


def get_market_state(market_key: str) -> dict:
    state = RUNTIME_STATE.get(market_key, {})
    return sanitize_market_state(state)


def set_market_state(market_key: str, state: dict) -> None:
    RUNTIME_STATE[market_key] = sanitize_market_state(state)


def save_runtime_state() -> None:
    state_file = get_state_file()
    payload = {"markets": RUNTIME_STATE}

    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print("Failed to save runtime state:", e)
        activity_logger.exception("Failed to save runtime state")


def load_runtime_state() -> None:
    global RUNTIME_STATE

    state_file = get_state_file()
    if not state_file.exists():
        RUNTIME_STATE = {}
        return

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        if isinstance(loaded, dict) and "markets" in loaded and isinstance(loaded["markets"], dict):
            raw_states = loaded["markets"]
        elif isinstance(loaded, dict) and any(
            key in loaded
            for key in {
                "last_processed_candle",
                "current_position",
                "current_entry_price",
                "current_stop_loss_price",
            }
        ):
            first_market = normalize_market(get_markets()[0])
            raw_states = {first_market["market_key"]: loaded}
        elif isinstance(loaded, dict):
            raw_states = loaded
        else:
            raw_states = {}

        RUNTIME_STATE = {
            str(market_key): sanitize_market_state(state if isinstance(state, dict) else {})
            for market_key, state in raw_states.items()
        }

        print("Loaded runtime state:", RUNTIME_STATE)
        activity_logger.info("Loaded runtime state: {0}".format(RUNTIME_STATE))

    except Exception as e:
        print("Failed to load runtime state:", e)
        activity_logger.exception("Failed to load runtime state")
        RUNTIME_STATE = {}


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


def get_total_portfolio_equity(
    latest_price_by_base: dict,
    balances: dict,
    quote_coin: str,
) -> float:
    total_equity = get_available_quote_balance(quote_coin, balances)
    full_balance = balances.get("full_balance")

    if full_balance is None:
        return total_equity

    seen_base_coins = set()
    for market in get_markets():
        normalized = normalize_market(market)
        base_coin = normalized["base_coin"]

        if base_coin in seen_base_coins:
            continue
        seen_base_coins.add(base_coin)

        latest_price = safe_float(latest_price_by_base.get(base_coin), 0.0)
        if latest_price <= 0:
            continue

        free_base = safe_float(
            client.get_free_balance(base_coin, balance_snapshot=full_balance)
        )
        total_equity += free_base * latest_price

    return total_equity


def compute_entry_qty(
    latest_price: float,
    total_equity: float,
    target_alloc_pct: float,
) -> float:
    min_qty = get_min_qty()
    qty_decimals = get_qty_decimals()

    if latest_price <= 0 or total_equity <= 0 or target_alloc_pct <= 0:
        return 0.0

    target_notional = total_equity * target_alloc_pct
    raw_qty = target_notional / latest_price
    qty = round_down(raw_qty, qty_decimals)

    if qty < min_qty:
        return 0.0

    return qty


def compute_top_up_qty(
    latest_price: float,
    current_base: float,
    total_equity: float,
    target_alloc_pct: float,
):
    min_qty = get_min_qty()
    qty_decimals = get_qty_decimals()

    target_qty = compute_entry_qty(latest_price, total_equity, target_alloc_pct)

    if target_qty <= 0:
        return 0.0, target_qty

    gap_qty = round_down(max(target_qty - current_base, 0.0), qty_decimals)

    if gap_qty < min_qty:
        return 0.0, target_qty

    return gap_qty, target_qty


def compute_exit_qty(free_base: float) -> float:
    min_qty = get_min_qty()
    qty_decimals = get_qty_decimals()
    sell_buffer_ratio = get_sell_buffer_ratio()
    close_full_position_on_exit = get_close_full_position_on_exit()

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


def build_market_snapshot(market: dict, signal_kwargs: dict) -> Optional[dict]:
    interval = get_str_setting("INTERVAL", "15m")
    limit = get_int_setting("LIMIT", 3000)

    symbol = market["binance_symbol"]
    pair = market["roostoo_pair"]

    print("\n==============================")
    print("Loading market:", pair)
    print("==============================")

    activity_logger.info(
        "Loading Binance data for symbol={0}, interval={1}, limit={2}".format(
            symbol, interval, limit
        )
    )
    df = load_binance_klines(symbol=symbol, interval=interval, limit=limit)

    activity_logger.info(
        "Generating VWAP signal for pair={0} with kwargs={1}".format(
            pair, signal_kwargs
        )
    )
    df = generate_vwap_signal(df, **signal_kwargs)

    print("Rows in df for {0}: {1}".format(pair, len(df)))

    if len(df) < 3:
        msg = "Not enough rows to evaluate closed-candle signal for {0}.".format(pair)
        print(msg)
        activity_logger.info(msg)
        return None

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
        msg = "Missing required columns for {0}: {1}".format(pair, missing_cols)
        print(msg)
        activity_logger.info(msg)
        return None

    if df[required_cols].tail(3).isnull().any().any():
        msg = "Latest rows contain NaN values for {0}. Skipping.".format(pair)
        print(msg)
        activity_logger.info(msg)
        return None

    prev_row = df.iloc[-3]
    latest_row = df.iloc[-2]

    latest_close = safe_float(latest_row["close"], 0.0)
    candle_time = str(latest_row["close_time"])
    prev_signal = int(prev_row["signal"])
    latest_signal = int(latest_row["signal"])

    print("\nLatest rows for {0}:".format(pair))
    print(df[required_cols].tail(5))
    print("Latest closed candle_time =", candle_time)
    print("prev_signal =", prev_signal)
    print("latest_signal =", latest_signal)

    return {
        "market": market,
        "df": df,
        "prev_row": prev_row,
        "latest_row": latest_row,
        "latest_close": latest_close,
        "candle_time": candle_time,
        "prev_signal": prev_signal,
        "latest_signal": latest_signal,
    }


def process_market(snapshot: dict, latest_price_by_base: dict, signal_kwargs: dict) -> None:
    market = snapshot["market"]
    pair = market["roostoo_pair"]
    symbol = market["binance_symbol"]
    base_coin = market["base_coin"]
    quote_coin = market["quote_coin"]
    target_alloc_pct = market["target_alloc_pct"]
    market_key = market["market_key"]

    interval = get_str_setting("INTERVAL", "15m")
    stop_loss_pct = get_stop_loss_pct()
    top_up_threshold_ratio = get_top_up_threshold_ratio()

    latest_row = snapshot["latest_row"]
    latest_close = snapshot["latest_close"]
    candle_time = snapshot["candle_time"]
    prev_signal = snapshot["prev_signal"]
    latest_signal = snapshot["latest_signal"]

    state = get_market_state(market_key)
    current_position = state["current_position"]
    current_entry_price = state["current_entry_price"]
    current_stop_loss_price = state["current_stop_loss_price"]

    print("\nProcessing market:", pair)
    print("Stored state:", state)

    if state["last_processed_candle"] == candle_time:
        msg = "Closed candle {0} for {1} already processed. Skipping.".format(
            candle_time, pair
        )
        print(msg)
        activity_logger.info(msg)
        return

    if prev_signal not in (0, 1) or latest_signal not in (0, 1):
        msg = (
            "Unexpected signal values detected for {0}. "
            "This main.py assumes long-only signals: 0 = flat, 1 = long."
        ).format(pair)
        print(msg)
        activity_logger.info(msg)
        state["last_processed_candle"] = candle_time
        set_market_state(market_key, state)
        save_runtime_state()
        return

    reconciliation_balances = log_balances(
        base_coin,
        quote_coin,
        prefix="Checking balances for state reconciliation ({0})...".format(pair),
        force_refresh=True,
    )
    require_balance_snapshot(reconciliation_balances, "state reconciliation for {0}".format(pair))

    live_base_qty = safe_float(reconciliation_balances.get("free_base"), 0.0)
    live_position = infer_position_from_base_balance(live_base_qty)

    if current_position is None:
        current_position = live_position
        msg = "Initial CURRENT_POSITION for {0} = {1}".format(pair, current_position)
        print(msg)
        activity_logger.info(msg)
    elif current_position != live_position:
        msg = (
            "Reconciling CURRENT_POSITION for {0} from runtime state {1} "
            "to live balance position {2}. live_base_qty={3}"
        ).format(pair, current_position, live_position, live_base_qty)
        print(msg)
        activity_logger.warning(msg)
        current_position = live_position

    if current_position == 1 and current_entry_price is None and latest_close > 0:
        current_entry_price = latest_close
        current_stop_loss_price = latest_close * (1 - stop_loss_pct)

        msg = (
            "Position detected for {0} but no saved entry price found. "
            "Bootstrapping stop loss from latest close. "
            "entry_price={1}, stop_loss={2}"
        ).format(pair, current_entry_price, current_stop_loss_price)
        print(msg)
        activity_logger.warning(msg)

    side = None
    signal_reason = None
    trade_qty = 0.0
    buy_was_top_up = False
    target_qty_before_trade = 0.0
    total_equity_before_trade = 0.0
    pre_trade_base_qty = live_base_qty

    if (
        current_position == 1
        and current_stop_loss_price is not None
        and latest_close > 0
        and latest_close <= current_stop_loss_price
    ):
        trade_qty = compute_exit_qty(live_base_qty)

        print("Computed STOP-LOSS SELL qty:", trade_qty)
        print("Free base balance:", live_base_qty)
        print("Current entry price:", current_entry_price)
        print("Current stop loss price:", current_stop_loss_price)
        print("Latest close:", latest_close)

        activity_logger.info(
            "STOP-LOSS SELL sizing for {0}: order_qty={1}, free_base={2}, "
            "entry_price={3}, stop_loss_price={4}, latest_close={5}".format(
                pair,
                trade_qty,
                live_base_qty,
                current_entry_price,
                current_stop_loss_price,
                latest_close,
            )
        )

        if trade_qty <= 0:
            msg = "Skip STOP-LOSS SELL for {0}: computed exit quantity is too small.".format(pair)
            print(msg)
            activity_logger.info(msg)
            state["last_processed_candle"] = candle_time
            state["current_position"] = current_position
            state["current_entry_price"] = current_entry_price
            state["current_stop_loss_price"] = current_stop_loss_price
            set_market_state(market_key, state)
            save_runtime_state()
            return

        side = "SELL"
        signal_reason = (
            "Stop loss hit: latest close {0} <= stop loss {1}".format(
                latest_close, current_stop_loss_price
            )
        )

    elif current_position == 0 and latest_signal == 1:
        available_quote = get_available_quote_balance(quote_coin, reconciliation_balances)
        total_equity_before_trade = get_total_portfolio_equity(
            latest_price_by_base=latest_price_by_base,
            balances=reconciliation_balances,
            quote_coin=quote_coin,
        )
        trade_qty = compute_entry_qty(
            latest_price=latest_close,
            total_equity=total_equity_before_trade,
            target_alloc_pct=target_alloc_pct,
        )
        target_qty_before_trade = trade_qty
        estimated_cost = trade_qty * latest_close

        print("Portfolio total equity:", total_equity_before_trade)
        print("Target allocation pct:", target_alloc_pct)
        print("Computed BUY qty:", trade_qty)
        print("Estimated BUY cost:", estimated_cost)
        print("Available quote balance:", available_quote)

        activity_logger.info(
            "BUY sizing for {0}: total_equity={1}, target_alloc_pct={2}, "
            "order_qty={3}, estimated_cost={4}, available_quote={5}".format(
                pair,
                total_equity_before_trade,
                target_alloc_pct,
                trade_qty,
                estimated_cost,
                available_quote,
            )
        )

        if latest_close <= 0:
            msg = "Skip BUY for {0}: invalid latest close price.".format(pair)
            print(msg)
            activity_logger.info(msg)
            state["last_processed_candle"] = candle_time
            state["current_position"] = current_position
            state["current_entry_price"] = current_entry_price
            state["current_stop_loss_price"] = current_stop_loss_price
            set_market_state(market_key, state)
            save_runtime_state()
            return

        if trade_qty <= 0:
            msg = "Skip BUY for {0}: computed order quantity is too small.".format(pair)
            print(msg)
            activity_logger.info(msg)
            state["last_processed_candle"] = candle_time
            state["current_position"] = current_position
            state["current_entry_price"] = current_entry_price
            state["current_stop_loss_price"] = current_stop_loss_price
            set_market_state(market_key, state)
            save_runtime_state()
            return

        if available_quote < estimated_cost:
            msg = (
                "Skip BUY for {0}: available quote balance {1} is below estimated cost {2}"
            ).format(pair, available_quote, estimated_cost)
            print(msg)
            activity_logger.info(msg)
            state["last_processed_candle"] = candle_time
            state["current_position"] = current_position
            state["current_entry_price"] = current_entry_price
            state["current_stop_loss_price"] = current_stop_loss_price
            set_market_state(market_key, state)
            save_runtime_state()
            return

        side = "BUY"
        if prev_signal == 0:
            signal_reason = "Signal flipped from 0 to 1 on latest closed candle"
        else:
            signal_reason = "Flat while signal is still 1, buying back to target allocation"

    elif current_position == 1 and latest_signal == 1:
        available_quote = get_available_quote_balance(quote_coin, reconciliation_balances)
        total_equity_before_trade = get_total_portfolio_equity(
            latest_price_by_base=latest_price_by_base,
            balances=reconciliation_balances,
            quote_coin=quote_coin,
        )
        trade_qty, target_qty_before_trade = compute_top_up_qty(
            latest_price=latest_close,
            current_base=live_base_qty,
            total_equity=total_equity_before_trade,
            target_alloc_pct=target_alloc_pct,
        )

        needs_top_up = (
            target_qty_before_trade > 0
            and live_base_qty < target_qty_before_trade * top_up_threshold_ratio
        )
        estimated_cost = trade_qty * latest_close

        print("Portfolio total equity:", total_equity_before_trade)
        print("Current base qty:", live_base_qty)
        print("Target allocation pct:", target_alloc_pct)
        print("Target qty:", target_qty_before_trade)
        print("Computed TOP-UP BUY qty:", trade_qty)
        print("Estimated TOP-UP BUY cost:", estimated_cost)
        print("Available quote balance:", available_quote)

        activity_logger.info(
            "TOP-UP BUY sizing for {0}: total_equity={1}, target_alloc_pct={2}, "
            "current_base={3}, target_qty={4}, top_up_qty={5}, estimated_cost={6}, available_quote={7}".format(
                pair,
                total_equity_before_trade,
                target_alloc_pct,
                live_base_qty,
                target_qty_before_trade,
                trade_qty,
                estimated_cost,
                available_quote,
            )
        )

        if latest_close <= 0:
            msg = "Skip TOP-UP BUY for {0}: invalid latest close price.".format(pair)
            print(msg)
            activity_logger.info(msg)
            state["last_processed_candle"] = candle_time
            state["current_position"] = current_position
            state["current_entry_price"] = current_entry_price
            state["current_stop_loss_price"] = current_stop_loss_price
            set_market_state(market_key, state)
            save_runtime_state()
            return

        if not needs_top_up:
            msg = (
                "No top-up needed for {0}. current_base={1}, target_qty={2}, threshold_ratio={3}"
            ).format(pair, live_base_qty, target_qty_before_trade, top_up_threshold_ratio)
            print(msg)
            activity_logger.info(msg)
            state["last_processed_candle"] = candle_time
            state["current_position"] = current_position
            state["current_entry_price"] = current_entry_price
            state["current_stop_loss_price"] = current_stop_loss_price
            set_market_state(market_key, state)
            save_runtime_state()
            return

        if trade_qty <= 0:
            msg = "Skip TOP-UP BUY for {0}: computed top-up quantity is too small.".format(pair)
            print(msg)
            activity_logger.info(msg)
            state["last_processed_candle"] = candle_time
            state["current_position"] = current_position
            state["current_entry_price"] = current_entry_price
            state["current_stop_loss_price"] = current_stop_loss_price
            set_market_state(market_key, state)
            save_runtime_state()
            return

        if available_quote < estimated_cost:
            msg = (
                "Skip TOP-UP BUY for {0}: available quote balance {1} is below estimated cost {2}"
            ).format(pair, available_quote, estimated_cost)
            print(msg)
            activity_logger.info(msg)
            state["last_processed_candle"] = candle_time
            state["current_position"] = current_position
            state["current_entry_price"] = current_entry_price
            state["current_stop_loss_price"] = current_stop_loss_price
            set_market_state(market_key, state)
            save_runtime_state()
            return

        side = "BUY"
        buy_was_top_up = True
        signal_reason = (
            "Top-up buy: current base {0} is below target qty {1}".format(
                live_base_qty, target_qty_before_trade
            )
        )

    elif current_position == 1 and prev_signal == 1 and latest_signal == 0:
        trade_qty = compute_exit_qty(live_base_qty)

        print("Computed SELL qty:", trade_qty)
        print("Free base balance:", live_base_qty)

        activity_logger.info(
            "SELL sizing for {0}: order_qty={1}, free_base={2}".format(
                pair, trade_qty, live_base_qty
            )
        )

        if trade_qty <= 0:
            msg = "Skip SELL for {0}: computed exit quantity is too small.".format(pair)
            print(msg)
            activity_logger.info(msg)
            state["last_processed_candle"] = candle_time
            state["current_position"] = current_position
            state["current_entry_price"] = current_entry_price
            state["current_stop_loss_price"] = current_stop_loss_price
            set_market_state(market_key, state)
            save_runtime_state()
            return

        side = "SELL"
        signal_reason = "Signal flipped from 1 to 0 on latest closed candle"

    if side is None:
        msg = (
            "No trade signal for {0} on candle {1}. prev_signal={2}, latest_signal={3}, current_position={4}"
        ).format(pair, candle_time, prev_signal, latest_signal, current_position)
        print(msg)
        activity_logger.info(msg)
        state["last_processed_candle"] = candle_time
        state["current_position"] = current_position
        state["current_entry_price"] = current_entry_price
        state["current_stop_loss_price"] = current_stop_loss_price
        set_market_state(market_key, state)
        save_runtime_state()
        return

    position_before_trade = current_position
    entry_price_before_trade = current_entry_price
    stop_loss_price_before_trade = current_stop_loss_price

    print("\nPlacing {0} order for {1}...".format(side, pair))
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
        prefix="Balances after order ({0}):".format(pair),
        force_refresh=True,
    )
    require_balance_snapshot(post_trade_balances, "post-trade balance check for {0}".format(pair))

    post_trade_base_qty = safe_float(post_trade_balances["free_base"], 0.0)
    position_after_trade = infer_position_from_base_balance(post_trade_base_qty)

    explicit_failure = has_explicit_failure(order_response) or has_explicit_failure(
        order_query
    )
    explicit_success = (
        has_explicit_success(order_response)
        or has_explicit_success(order_query)
        or bool(order_id)
    )

    if side == "BUY":
        if position_before_trade == 0:
            balance_confirms_trade = (
                position_after_trade == 1 and post_trade_base_qty > pre_trade_base_qty
            )
        else:
            balance_confirms_trade = post_trade_base_qty > pre_trade_base_qty + 1e-12
    else:
        if get_close_full_position_on_exit():
            balance_confirms_trade = position_after_trade == 0
        else:
            balance_confirms_trade = post_trade_base_qty < pre_trade_base_qty - 1e-12

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

    state["current_position"] = position_after_trade
    state["last_processed_candle"] = candle_time

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
                current_entry_price = (
                    (pre_trade_base_qty * entry_price_before_trade)
                    + (trade_qty * fill_price_for_state)
                ) / total_qty
            else:
                current_entry_price = fill_price_for_state

            current_stop_loss_price = current_entry_price * (1 - stop_loss_pct)
        else:
            current_entry_price = None
            current_stop_loss_price = None

        state["current_entry_price"] = current_entry_price
        state["current_stop_loss_price"] = current_stop_loss_price
        set_market_state(market_key, state)
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
                "market_key": market_key,
                "pair": pair,
                "base_coin": base_coin,
                "quote_coin": quote_coin,
                "target_alloc_pct": target_alloc_pct,
                "portfolio_total_equity_before_trade": total_equity_before_trade,
                "interval": interval,
                "candle_time": candle_time,
                "prev_signal": prev_signal,
                "latest_signal": latest_signal,
                "current_position_before_trade": position_before_trade,
                "current_position_after_trade": position_after_trade,
                "trade_qty": trade_qty,
                "buy_was_top_up": buy_was_top_up,
                "pre_trade_base_qty": pre_trade_base_qty,
                "post_trade_base_qty": post_trade_base_qty,
                "target_qty_before_trade": target_qty_before_trade,
                "entry_price_before_trade": entry_price_before_trade,
                "stop_loss_price_before_trade": stop_loss_price_before_trade,
                "entry_price_after_trade": current_entry_price,
                "stop_loss_price_after_trade": current_stop_loss_price,
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
            "Placed {0} order for {1} {2}. order_id={3}, fill_price={4}, reason={5}, "
            "current_position={6}, last_processed_candle={7}".format(
                side,
                trade_qty,
                pair,
                order_id,
                actual_trade_price,
                signal_reason,
                position_after_trade,
                candle_time,
            )
        )

        print("Updated state for {0}:".format(pair))
        print(get_market_state(market_key))
    else:
        state["current_entry_price"] = current_entry_price
        state["current_stop_loss_price"] = current_stop_loss_price
        set_market_state(market_key, state)
        save_runtime_state()

        msg = (
            "Order may not have succeeded cleanly for {0}. side={1}, order_id={2}, "
            "explicit_failure={3}, explicit_success={4}, position_before_trade={5}, "
            "position_after_trade={6}"
        ).format(
            pair,
            side,
            order_id,
            explicit_failure,
            explicit_success,
            position_before_trade,
            position_after_trade,
        )
        print(msg)
        activity_logger.warning(msg)


def run_once():
    print("Entered run_once")

    signal_kwargs = build_signal_kwargs()
    normalized_markets = [normalize_market(market) for market in get_markets()]

    quote_coins = {market["quote_coin"] for market in normalized_markets}
    if len(quote_coins) > 1:
        raise ValueError(
            "This main.py assumes all configured markets share the same quote coin."
        )

    snapshots = []
    for market in normalized_markets:
        snapshot = build_market_snapshot(market, signal_kwargs)
        if snapshot is not None:
            snapshots.append(snapshot)

    if not snapshots:
        msg = "No valid market snapshots available this cycle."
        print(msg)
        activity_logger.info(msg)
        return

    latest_price_by_base = {
        snapshot["market"]["base_coin"]: snapshot["latest_close"] for snapshot in snapshots
    }

    for snapshot in snapshots:
        process_market(
            snapshot=snapshot,
            latest_price_by_base=latest_price_by_base,
            signal_kwargs=signal_kwargs,
        )


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
