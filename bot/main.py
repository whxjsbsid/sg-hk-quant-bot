# bot/strategy/main.py

import inspect
import json
import math
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from bot.config import settings
from bot.data.binance_loader import load_binance_klines
from bot.execution.roostoo_client import RoostooClient
from bot.logs.activity_logger import setup_activity_logger
from bot.logs.trade_logger import TradeLogger
from bot.strategy.vwap_reversion import generate_vwap_signal


load_dotenv()

client = RoostooClient()
trade_logger = TradeLogger()
activity_logger = setup_activity_logger()

RUNTIME_STATE: dict[str, dict[str, Any]] = {}


def get_setting(name: str, default: Any = None) -> Any:
    return getattr(settings, name, default)


def get_str_setting(name: str, default: str) -> str:
    value = get_setting(name, default)
    return default if value is None else str(value)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
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


def log_message(message: str, level: str = "info") -> None:
    print(message)
    getattr(activity_logger, level)(message)


def get_state_file() -> Path:
    return Path(get_str_setting("RUNTIME_STATE_FILE", "bot/runtime_state.json"))


def get_markets() -> list[dict[str, Any]]:
    markets = get_setting("MARKETS", [])
    if not isinstance(markets, list) or not markets:
        raise ValueError("settings.MARKETS must be a non-empty list.")
    return markets


def normalize_market(market: dict[str, Any]) -> dict[str, Any]:
    pair = str(market["roostoo_pair"]).strip().upper()
    base_coin = str(market["base_coin"]).strip().upper()

    if market.get("quote_coin") not in (None, ""):
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


def get_normalized_markets() -> list[dict[str, Any]]:
    return [normalize_market(market) for market in get_markets()]


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
    factor = 10 ** max(decimals, 0)
    return math.floor(value * factor) / factor


def sanitize_market_state(state: dict[str, Any]) -> dict[str, Any]:
    current_position = state.get("current_position")
    if current_position not in (0, 1):
        current_position = None

    entry_price = safe_float(state.get("current_entry_price"), 0.0)
    stop_loss_price = safe_float(state.get("current_stop_loss_price"), 0.0)

    return {
        "last_processed_candle": state.get("last_processed_candle"),
        "current_position": current_position,
        "current_entry_price": entry_price if entry_price > 0 else None,
        "current_stop_loss_price": stop_loss_price if stop_loss_price > 0 else None,
    }


def get_market_state(market_key: str) -> dict[str, Any]:
    return sanitize_market_state(RUNTIME_STATE.get(market_key, {}))


def set_market_state(market_key: str, state: dict[str, Any]) -> None:
    RUNTIME_STATE[market_key] = sanitize_market_state(state)


def save_runtime_state() -> None:
    state_file = get_state_file()
    payload = {"markets": RUNTIME_STATE}

    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
    except Exception:
        activity_logger.exception("Failed to save runtime state")


def load_runtime_state() -> None:
    global RUNTIME_STATE

    state_file = get_state_file()
    if not state_file.exists():
        RUNTIME_STATE = {}
        return

    try:
        with open(state_file, "r", encoding="utf-8") as file:
            loaded = json.load(file)

        if isinstance(loaded, dict) and isinstance(loaded.get("markets"), dict):
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
            first_market = get_normalized_markets()[0]
            raw_states = {first_market["market_key"]: loaded}
        elif isinstance(loaded, dict):
            raw_states = loaded
        else:
            raw_states = {}

        RUNTIME_STATE = {
            str(market_key): sanitize_market_state(state if isinstance(state, dict) else {})
            for market_key, state in raw_states.items()
        }
        log_message(f"Loaded runtime state: {RUNTIME_STATE}")
    except Exception:
        activity_logger.exception("Failed to load runtime state")
        RUNTIME_STATE = {}


def save_market_progress(
    market_key: str,
    candle_time: str,
    current_position: Optional[int],
    current_entry_price: Optional[float],
    current_stop_loss_price: Optional[float],
) -> None:
    set_market_state(
        market_key,
        {
            "last_processed_candle": candle_time,
            "current_position": current_position,
            "current_entry_price": current_entry_price,
            "current_stop_loss_price": current_stop_loss_price,
        },
    )
    save_runtime_state()


def find_first_value(obj: Any, key_names: set[str]) -> Any:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in key_names and value not in (None, ""):
                return value
        for value in obj.values():
            found = find_first_value(value, key_names)
            if found not in (None, ""):
                return found

    if isinstance(obj, list):
        for item in obj:
            found = find_first_value(item, key_names)
            if found not in (None, ""):
                return found

    return None


def extract_order_id(obj: Any) -> str:
    value = find_first_value(obj, {"orderid", "order_id", "id"})
    return "" if value in (None, "") else str(value)


def extract_order_status(obj: Any) -> str:
    value = find_first_value(obj, {"status", "orderstatus", "state", "order_state"})
    return "" if value in (None, "") else str(value).strip().upper()


def extract_fill_price(*objs: Any, fallback: Optional[float] = None) -> Optional[float]:
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
        price = safe_float(value, 0.0)
        if price > 0:
            return price

    return fallback


def has_explicit_failure(obj: Any) -> bool:
    if obj is None:
        return False

    failure_statuses = {
        "REJECTED",
        "FAILED",
        "CANCELLED",
        "EXPIRED",
        "ERROR",
        "INVALID",
    }
    if extract_order_status(obj) in failure_statuses:
        return True

    message_value = find_first_value(
        obj,
        {"message", "msg", "error", "errormsg", "error_message", "detail"},
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
    return isinstance(success_value, bool) and success_value is False


def has_explicit_success(obj: Any) -> bool:
    if obj is None:
        return False

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
    if extract_order_status(obj) in success_statuses:
        return True

    success_value = find_first_value(obj, {"success", "ok"})
    if isinstance(success_value, bool) and success_value is True:
        return True

    return bool(extract_order_id(obj))


def log_balances(
    base_coin: str,
    quote_coin: str,
    prefix: str = "",
    force_refresh: bool = False,
) -> dict[str, Any]:
    try:
        full_balance = client.get_balance(force_refresh=force_refresh)
        free_base = safe_float(client.get_free_balance(base_coin, balance_snapshot=full_balance))
        free_quote = safe_float(client.get_free_balance(quote_coin, balance_snapshot=full_balance))
        free_usd = safe_float(client.get_free_balance("USD", balance_snapshot=full_balance))
        free_usdt = safe_float(client.get_free_balance("USDT", balance_snapshot=full_balance))

        if prefix:
            log_message(prefix)

        print("Full balance:")
        print(full_balance)
        print(f"Free {base_coin} balance: {free_base}")
        print(f"Free {quote_coin} balance: {free_quote}")
        print(f"Free USD balance: {free_usd}")
        print(f"Free USDT balance: {free_usdt}")

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
    except Exception:
        activity_logger.exception("Failed to fetch balances")
        return {
            "full_balance": None,
            "free_base": 0.0,
            "free_quote": 0.0,
            "free_usd": 0.0,
            "free_usdt": 0.0,
        }


def require_balance_snapshot(balances: dict[str, Any], context: str) -> None:
    if balances.get("full_balance") is None:
        raise RuntimeError(
            f"Failed to fetch balance during {context}. "
            "Check Roostoo API auth before running the bot."
        )


def get_available_quote_balance(quote_coin: str, balances: dict[str, Any]) -> float:
    free_quote = safe_float(balances.get("free_quote"), 0.0)
    free_usd = safe_float(balances.get("free_usd"), 0.0)
    free_usdt = safe_float(balances.get("free_usdt"), 0.0)

    if quote_coin == "USD":
        return max(free_quote, free_usd) + free_usdt
    if quote_coin == "USDT":
        return max(free_quote, free_usdt)
    return free_quote


def get_total_portfolio_equity(
    latest_price_by_base: dict[str, float],
    balances: dict[str, Any],
    quote_coin: str,
) -> float:
    total_equity = get_available_quote_balance(quote_coin, balances)
    full_balance = balances.get("full_balance")

    if full_balance is None:
        return total_equity

    seen_base_coins: set[str] = set()
    for market in get_normalized_markets():
        base_coin = market["base_coin"]
        if base_coin in seen_base_coins:
            continue

        seen_base_coins.add(base_coin)
        latest_price = safe_float(latest_price_by_base.get(base_coin), 0.0)
        if latest_price <= 0:
            continue

        free_base = safe_float(client.get_free_balance(base_coin, balance_snapshot=full_balance))
        total_equity += free_base * latest_price

    return total_equity


def compute_entry_qty(
    latest_price: float,
    total_equity: float,
    target_alloc_pct: float,
) -> float:
    if latest_price <= 0 or total_equity <= 0 or target_alloc_pct <= 0:
        return 0.0

    target_notional = total_equity * target_alloc_pct
    raw_qty = target_notional / latest_price
    qty = round_down(raw_qty, get_qty_decimals())
    return qty if qty >= get_min_qty() else 0.0


def compute_top_up_qty(
    latest_price: float,
    current_base: float,
    total_equity: float,
    target_alloc_pct: float,
) -> tuple[float, float]:
    target_qty = compute_entry_qty(latest_price, total_equity, target_alloc_pct)
    if target_qty <= 0:
        return 0.0, target_qty

    gap_qty = round_down(max(target_qty - current_base, 0.0), get_qty_decimals())
    if gap_qty < get_min_qty():
        return 0.0, target_qty

    return gap_qty, target_qty


def compute_exit_qty(free_base: float) -> float:
    if get_close_full_position_on_exit():
        qty = round_down(free_base, get_qty_decimals())
    else:
        qty = round_down(free_base * get_sell_buffer_ratio(), get_qty_decimals())

    return qty if qty >= get_min_qty() else 0.0


def infer_position_from_base_balance(free_base: float) -> int:
    threshold = max(get_min_qty() * get_holding_threshold_ratio(), 1e-12)
    return 1 if free_base >= threshold else 0


def query_order_safely(pair: str, order_id: str = "") -> Any:
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
    except Exception:
        activity_logger.exception("Order query failed")
        return None


def build_signal_kwargs() -> dict[str, Any]:
    setting_map = {
        "window": "VWAP_WINDOW",
        "lower_std_mult": "LOWER_STD_MULT",
        "exit_std_mult": "EXIT_STD_MULT",
        "strong_exit_std_mult": "STRONG_EXIT_STD_MULT",
        "trend_window": "TREND_WINDOW",
    }

    signature = inspect.signature(generate_vwap_signal)
    kwargs: dict[str, Any] = {}

    for arg_name, setting_name in setting_map.items():
        if arg_name not in signature.parameters:
            continue

        parameter = signature.parameters[arg_name]
        default = None if parameter.default is inspect._empty else parameter.default
        value = get_setting(setting_name, default)
        if value is not None:
            kwargs[arg_name] = value

    return kwargs


def build_market_snapshot(
    market: dict[str, Any],
    signal_kwargs: dict[str, Any],
) -> Optional[dict[str, Any]]:
    interval = get_str_setting("INTERVAL", "15m")
    limit = get_int_setting("LIMIT", 3000)

    symbol = market["binance_symbol"]
    pair = market["roostoo_pair"]

    print("\n==============================")
    print(f"Loading market: {pair}")
    print("==============================")

    activity_logger.info(
        f"Loading Binance data for symbol={symbol}, interval={interval}, limit={limit}"
    )
    df = load_binance_klines(symbol=symbol, interval=interval, limit=limit)

    activity_logger.info(f"Generating VWAP signal for pair={pair} with kwargs={signal_kwargs}")
    df = generate_vwap_signal(df, **signal_kwargs)

    print(f"Rows in df for {pair}: {len(df)}")

    if len(df) < 3:
        log_message(f"Not enough rows to evaluate closed-candle signal for {pair}.")
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
        log_message(f"Missing required columns for {pair}: {missing_cols}")
        return None

    if df[required_cols].tail(3).isnull().any().any():
        log_message(f"Latest rows contain NaN values for {pair}. Skipping.")
        return None

    prev_row = df.iloc[-3]
    latest_row = df.iloc[-2]

    latest_close = safe_float(latest_row["close"], 0.0)
    candle_time = str(latest_row["close_time"])
    prev_signal = int(prev_row["signal"])
    latest_signal = int(latest_row["signal"])

    print(f"\nLatest rows for {pair}:")
    print(df[required_cols].tail(5))
    print(f"Latest closed candle_time = {candle_time}")
    print(f"prev_signal = {prev_signal}")
    print(f"latest_signal = {latest_signal}")

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


def process_market(
    snapshot: dict[str, Any],
    latest_price_by_base: dict[str, float],
    signal_kwargs: dict[str, Any],
) -> None:
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

    print(f"\nProcessing market: {pair}")
    print(f"Stored state: {state}")

    if state["last_processed_candle"] == candle_time:
        log_message(f"Closed candle {candle_time} for {pair} already processed. Skipping.")
        return

    if prev_signal not in (0, 1) or latest_signal not in (0, 1):
        log_message(
            f"Unexpected signal values detected for {pair}. "
            "This main.py assumes long-only signals: 0 = flat, 1 = long."
        )
        save_market_progress(
            market_key,
            candle_time,
            current_position,
            current_entry_price,
            current_stop_loss_price,
        )
        return

    reconciliation_balances = log_balances(
        base_coin,
        quote_coin,
        prefix=f"Checking balances for state reconciliation ({pair})...",
        force_refresh=True,
    )
    require_balance_snapshot(reconciliation_balances, f"state reconciliation for {pair}")

    live_base_qty = safe_float(reconciliation_balances.get("free_base"), 0.0)
    live_position = infer_position_from_base_balance(live_base_qty)

    if current_position is None:
        current_position = live_position
        log_message(f"Initial CURRENT_POSITION for {pair} = {current_position}")
    elif current_position != live_position:
        log_message(
            f"Reconciling CURRENT_POSITION for {pair} from runtime state {current_position} "
            f"to live balance position {live_position}. live_base_qty={live_base_qty}",
            level="warning",
        )
        current_position = live_position

    if current_position == 1 and current_entry_price is None and latest_close > 0:
        current_entry_price = latest_close
        current_stop_loss_price = latest_close * (1 - stop_loss_pct)
        log_message(
            f"Position detected for {pair} but no saved entry price found. "
            "Bootstrapping stop loss from latest close. "
            f"entry_price={current_entry_price}, stop_loss={current_stop_loss_price}",
            level="warning",
        )

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

        print(f"Computed STOP-LOSS SELL qty: {trade_qty}")
        print(f"Free base balance: {live_base_qty}")
        print(f"Current entry price: {current_entry_price}")
        print(f"Current stop loss price: {current_stop_loss_price}")
        print(f"Latest close: {latest_close}")

        activity_logger.info(
            f"STOP-LOSS SELL sizing for {pair}: order_qty={trade_qty}, "
            f"free_base={live_base_qty}, entry_price={current_entry_price}, "
            f"stop_loss_price={current_stop_loss_price}, latest_close={latest_close}"
        )

        if trade_qty <= 0:
            log_message(f"Skip STOP-LOSS SELL for {pair}: computed exit quantity is too small.")
            save_market_progress(
                market_key,
                candle_time,
                current_position,
                current_entry_price,
                current_stop_loss_price,
            )
            return

        side = "SELL"
        signal_reason = (
            f"Stop loss hit: latest close {latest_close} <= stop loss {current_stop_loss_price}"
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

        print(f"Portfolio total equity: {total_equity_before_trade}")
        print(f"Target allocation pct: {target_alloc_pct}")
        print(f"Computed BUY qty: {trade_qty}")
        print(f"Estimated BUY cost: {estimated_cost}")
        print(f"Available quote balance: {available_quote}")

        activity_logger.info(
            f"BUY sizing for {pair}: total_equity={total_equity_before_trade}, "
            f"target_alloc_pct={target_alloc_pct}, order_qty={trade_qty}, "
            f"estimated_cost={estimated_cost}, available_quote={available_quote}"
        )

        if latest_close <= 0:
            log_message(f"Skip BUY for {pair}: invalid latest close price.")
            save_market_progress(
                market_key,
                candle_time,
                current_position,
                current_entry_price,
                current_stop_loss_price,
            )
            return

        if trade_qty <= 0:
            log_message(f"Skip BUY for {pair}: computed order quantity is too small.")
            save_market_progress(
                market_key,
                candle_time,
                current_position,
                current_entry_price,
                current_stop_loss_price,
            )
            return

        if available_quote < estimated_cost:
            log_message(
                f"Skip BUY for {pair}: available quote balance {available_quote} "
                f"is below estimated cost {estimated_cost}"
            )
            save_market_progress(
                market_key,
                candle_time,
                current_position,
                current_entry_price,
                current_stop_loss_price,
            )
            return

        side = "BUY"
        signal_reason = (
            "Signal flipped from 0 to 1 on latest closed candle"
            if prev_signal == 0
            else "Flat while signal is still 1, buying back to target allocation"
        )

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

        print(f"Portfolio total equity: {total_equity_before_trade}")
        print(f"Current base qty: {live_base_qty}")
        print(f"Target allocation pct: {target_alloc_pct}")
        print(f"Target qty: {target_qty_before_trade}")
        print(f"Computed TOP-UP BUY qty: {trade_qty}")
        print(f"Estimated TOP-UP BUY cost: {estimated_cost}")
        print(f"Available quote balance: {available_quote}")

        activity_logger.info(
            f"TOP-UP BUY sizing for {pair}: total_equity={total_equity_before_trade}, "
            f"target_alloc_pct={target_alloc_pct}, current_base={live_base_qty}, "
            f"target_qty={target_qty_before_trade}, top_up_qty={trade_qty}, "
            f"estimated_cost={estimated_cost}, available_quote={available_quote}"
        )

        if latest_close <= 0:
            log_message(f"Skip TOP-UP BUY for {pair}: invalid latest close price.")
            save_market_progress(
                market_key,
                candle_time,
                current_position,
                current_entry_price,
                current_stop_loss_price,
            )
            return

        if not needs_top_up:
            log_message(
                f"No top-up needed for {pair}. current_base={live_base_qty}, "
                f"target_qty={target_qty_before_trade}, threshold_ratio={top_up_threshold_ratio}"
            )
            save_market_progress(
                market_key,
                candle_time,
                current_position,
                current_entry_price,
                current_stop_loss_price,
            )
            return

        if trade_qty <= 0:
            log_message(f"Skip TOP-UP BUY for {pair}: computed top-up quantity is too small.")
            save_market_progress(
                market_key,
                candle_time,
                current_position,
                current_entry_price,
                current_stop_loss_price,
            )
            return

        if available_quote < estimated_cost:
            log_message(
                f"Skip TOP-UP BUY for {pair}: available quote balance {available_quote} "
                f"is below estimated cost {estimated_cost}"
            )
            save_market_progress(
                market_key,
                candle_time,
                current_position,
                current_entry_price,
                current_stop_loss_price,
            )
            return

        side = "BUY"
        buy_was_top_up = True
        signal_reason = (
            f"Top-up buy: current base {live_base_qty} is below target qty {target_qty_before_trade}"
        )

    elif current_position == 1 and prev_signal == 1 and latest_signal == 0:
        trade_qty = compute_exit_qty(live_base_qty)

        print(f"Computed SELL qty: {trade_qty}")
        print(f"Free base balance: {live_base_qty}")

        activity_logger.info(
            f"SELL sizing for {pair}: order_qty={trade_qty}, free_base={live_base_qty}"
        )

        if trade_qty <= 0:
            log_message(f"Skip SELL for {pair}: computed exit quantity is too small.")
            save_market_progress(
                market_key,
                candle_time,
                current_position,
                current_entry_price,
                current_stop_loss_price,
            )
            return

        side = "SELL"
        signal_reason = "Signal flipped from 1 to 0 on latest closed candle"

    if side is None:
        log_message(
            f"No trade signal for {pair} on candle {candle_time}. prev_signal={prev_signal}, "
            f"latest_signal={latest_signal}, current_position={current_position}"
        )
        save_market_progress(
            market_key,
            candle_time,
            current_position,
            current_entry_price,
            current_stop_loss_price,
        )
        return

    position_before_trade = current_position
    entry_price_before_trade = current_entry_price
    stop_loss_price_before_trade = current_stop_loss_price

    print(f"\nPlacing {side} order for {pair}...")
    activity_logger.info(
        f"Placing {side} order for pair={pair}, quantity={trade_qty}, reason={signal_reason}"
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
        prefix=f"Balances after order ({pair}):",
        force_refresh=True,
    )
    require_balance_snapshot(post_trade_balances, f"post-trade balance check for {pair}")

    post_trade_base_qty = safe_float(post_trade_balances["free_base"], 0.0)
    position_after_trade = infer_position_from_base_balance(post_trade_base_qty)

    explicit_failure = has_explicit_failure(order_response) or has_explicit_failure(order_query)
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

    order_success = balance_confirms_trade or (explicit_success and not explicit_failure)

    actual_trade_price = extract_fill_price(
        order_query,
        order_response,
        fallback=latest_close if latest_close > 0 else None,
    )

    state["current_position"] = position_after_trade
    state["last_processed_candle"] = candle_time

    if order_success:
        fill_price_for_state = actual_trade_price if actual_trade_price is not None else latest_close

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
            f"Placed {side} order for {trade_qty} {pair}. order_id={order_id}, "
            f"fill_price={actual_trade_price}, reason={signal_reason}, "
            f"current_position={position_after_trade}, last_processed_candle={candle_time}"
        )

        print(f"Updated state for {pair}:")
        print(get_market_state(market_key))
        return

    state["current_entry_price"] = current_entry_price
    state["current_stop_loss_price"] = current_stop_loss_price
    set_market_state(market_key, state)
    save_runtime_state()

    log_message(
        f"Order may not have succeeded cleanly for {pair}. side={side}, order_id={order_id}, "
        f"explicit_failure={explicit_failure}, explicit_success={explicit_success}, "
        f"position_before_trade={position_before_trade}, position_after_trade={position_after_trade}",
        level="warning",
    )


def run_once() -> None:
    print("Entered run_once")

    signal_kwargs = build_signal_kwargs()
    normalized_markets = get_normalized_markets()

    quote_coins = {market["quote_coin"] for market in normalized_markets}
    if len(quote_coins) > 1:
        raise ValueError("This main.py assumes all configured markets share the same quote coin.")

    snapshots = []
    for market in normalized_markets:
        snapshot = build_market_snapshot(market, signal_kwargs)
        if snapshot is not None:
            snapshots.append(snapshot)

    if not snapshots:
        log_message("No valid market snapshots available this cycle.")
        return

    latest_price_by_base = {
        snapshot["market"]["base_coin"]: snapshot["latest_close"]
        for snapshot in snapshots
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
        print(f"Sleeping for {poll_seconds} seconds...\n")
        activity_logger.info(f"Sleeping for {poll_seconds} seconds")
        time.sleep(poll_seconds)
