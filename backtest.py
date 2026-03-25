import inspect
import math
from typing import Dict, List

import numpy as np
import pandas as pd

from bot.config import settings
from bot.data.binance_loader import load_binance_klines
from bot.strategy.vwap_reversion import generate_vwap_signal


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def round_down(value: float, decimals: int) -> float:
    factor = 10 ** max(decimals, 0)
    return math.floor(value * factor) / factor


def get_periods_per_year(interval: str) -> int:
    mapping = {
        "1d": 365,
        "1h": 24 * 365,
        "15m": 4 * 24 * 365,
        "5m": 12 * 24 * 365,
        "1m": 60 * 24 * 365,
    }
    return mapping.get(interval, 365)


def get_setting(name: str, default=None):
    return getattr(settings, name, default)


def get_str_setting(name: str, default: str) -> str:
    value = get_setting(name, default)
    if value is None:
        return default
    return str(value)


def get_int_setting(name: str, default: int) -> int:
    value = get_setting(name, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_float_setting(name: str, default: float) -> float:
    return safe_float(get_setting(name, default), default)


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


def get_markets() -> List[dict]:
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


def get_initial_cash() -> float:
    return max(get_float_setting("INITIAL_CASH", 0.0), 0.0)


def get_stop_loss_pct() -> float:
    return max(get_float_setting("STOP_LOSS_PCT", 0.0), 0.0)


def get_min_qty() -> float:
    return max(get_float_setting("MIN_QTY", 0.0), 0.0)


def get_qty_decimals() -> int:
    value = get_int_setting("QTY_DECIMALS", 8)
    return max(value, 0)


def get_sell_buffer_ratio() -> float:
    ratio = get_float_setting("SELL_BUFFER_RATIO", 1.0)
    return min(max(ratio, 0.0), 1.0)


def get_close_full_position_on_exit() -> bool:
    return get_bool_setting("CLOSE_FULL_POSITION_ON_EXIT", True)


def get_top_up_threshold_ratio() -> float:
    ratio = get_float_setting("TOP_UP_THRESHOLD_RATIO", 0.95)
    return min(max(ratio, 0.0), 1.0)


def get_interval() -> str:
    return get_str_setting("INTERVAL", "15m")


def get_limit() -> int:
    return get_int_setting("LIMIT", 3000)


def get_signal_kwargs() -> dict:
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


def compute_metrics(
    return_series: pd.Series,
    equity_series: pd.Series,
    periods_per_year: int,
) -> dict:
    r = return_series.dropna().copy()

    if len(r) == 0:
        return {
            "sharpe": 0.0,
            "sortino": 0.0,
            "calmar": 0.0,
            "composite": 0.0,
            "max_drawdown": 0.0,
            "annual_return": 0.0,
        }

    mean_return = r.mean()
    std_return = r.std(ddof=0)
    sharpe = 0.0 if std_return == 0 else (mean_return / std_return) * np.sqrt(periods_per_year)

    downside = r[r < 0]
    downside_std = downside.std(ddof=0)
    sortino = 0.0 if downside_std == 0 or np.isnan(downside_std) else (mean_return / downside_std) * np.sqrt(periods_per_year)

    rolling_max = equity_series.cummax()
    drawdown = (equity_series - rolling_max) / rolling_max
    max_drawdown = abs(drawdown.min()) if len(drawdown) > 0 else 0.0

    total_return = equity_series.iloc[-1] / equity_series.iloc[0] - 1
    n_periods = len(r)
    annual_return = (1 + total_return) ** (periods_per_year / n_periods) - 1 if n_periods > 0 else 0.0

    calmar = 0.0 if max_drawdown == 0 else annual_return / max_drawdown
    composite = 0.4 * sortino + 0.3 * sharpe + 0.3 * calmar

    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "composite": composite,
        "max_drawdown": max_drawdown,
        "annual_return": annual_return,
    }


def compute_trade_stats(
    trade_action_series: pd.Series,
    exit_reason_series: pd.Series,
    time_series: pd.Series,
) -> dict:
    actions = trade_action_series.fillna("")
    exits = exit_reason_series.fillna("")

    buy_entries = int((actions == "BUY").sum())
    top_up_buys = int((actions == "BUY_TOPUP").sum())
    sell_orders = int((actions == "SELL").sum())
    total_orders = buy_entries + top_up_buys + sell_orders
    round_trips = min(buy_entries, sell_orders)

    stop_loss_exits = int((exits == "stop_loss").sum())
    signal_exits = int((exits == "signal_exit").sum())

    if len(time_series) > 0:
        trade_dates = pd.to_datetime(time_series).dt.date
        active_days = int(trade_dates[actions != ""].nunique()) if total_orders > 0 else 0

        start_ts = pd.to_datetime(time_series.iloc[0])
        end_ts = pd.to_datetime(time_series.iloc[-1])
        sample_days = max((end_ts - start_ts).total_seconds() / 86400, 1e-9)
    else:
        active_days = 0
        sample_days = 0.0

    orders_per_day_all = total_orders / sample_days if sample_days > 0 else 0.0
    orders_per_active_day = total_orders / active_days if active_days > 0 else 0.0

    return {
        "entries": buy_entries,
        "top_up_buys": top_up_buys,
        "exits": sell_orders,
        "stop_loss_exits": stop_loss_exits,
        "signal_exits": signal_exits,
        "total_orders": total_orders,
        "round_trips": round_trips,
        "active_days": active_days,
        "orders_per_day_all": orders_per_day_all,
        "orders_per_active_day": orders_per_active_day,
        "sample_days": sample_days,
    }


def compute_total_equity(cash: float, market_states: Dict[str, dict], current_prices: Dict[str, float]) -> float:
    total_equity = cash
    for market_key, state in market_states.items():
        total_equity += safe_float(state["base_qty"], 0.0) * safe_float(current_prices.get(market_key), 0.0)
    return total_equity


def compute_target_qty(total_equity: float, close_price: float, target_alloc_pct: float) -> float:
    qty_decimals = get_qty_decimals()
    min_qty = get_min_qty()

    if close_price <= 0 or total_equity <= 0 or target_alloc_pct <= 0:
        return 0.0

    target_notional = total_equity * target_alloc_pct
    raw_qty = target_notional / close_price
    qty = round_down(raw_qty, qty_decimals)

    if qty < min_qty:
        return 0.0

    return qty


def compute_exit_qty(base_qty: float) -> float:
    qty_decimals = get_qty_decimals()
    min_qty = get_min_qty()
    sell_buffer_ratio = get_sell_buffer_ratio()
    close_full_position_on_exit = get_close_full_position_on_exit()

    if close_full_position_on_exit:
        qty = round_down(base_qty, qty_decimals)
    else:
        qty = round_down(base_qty * sell_buffer_ratio, qty_decimals)

    if qty <= 0:
        qty = round_down(base_qty, qty_decimals)

    if qty < min_qty:
        return 0.0

    return min(qty, base_qty)


def add_time_key(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "open_time" in out.columns:
        out["time_key"] = pd.to_datetime(out["open_time"])
    elif "close_time" in out.columns:
        out["time_key"] = pd.to_datetime(out["close_time"])
    else:
        out["time_key"] = pd.RangeIndex(len(out))
    return out


def load_market_frames(markets: List[dict], signal_kwargs: dict) -> Dict[str, pd.DataFrame]:
    interval = get_interval()
    limit = get_limit()
    frames = {}

    for market in markets:
        symbol = market["binance_symbol"]
        pair = market["roostoo_pair"]

        df = load_binance_klines(symbol=symbol, interval=interval, limit=limit)
        df = generate_vwap_signal(df, **signal_kwargs).copy()
        df = add_time_key(df)

        required_cols = [
            "time_key",
            "close",
            "signal",
            "vwap",
            "lower_band",
            "upper_band",
            "strong_upper_band",
        ]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns for {pair}: {missing_cols}")

        df = df.dropna(subset=["time_key", "close", "signal"]).sort_values("time_key").reset_index(drop=True)
        frames[market["market_key"]] = df

    return frames


def align_market_frames(frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    common_times = None
    for df in frames.values():
        current_times = set(df["time_key"].tolist())
        common_times = current_times if common_times is None else common_times & current_times

    if not common_times:
        raise ValueError("No overlapping timestamps across configured markets.")

    aligned = {}
    common_times = sorted(common_times)
    for market_key, df in frames.items():
        out = df[df["time_key"].isin(common_times)].copy()
        out = out.sort_values("time_key").reset_index(drop=True)
        aligned[market_key] = out

    lengths = {market_key: len(df) for market_key, df in aligned.items()}
    unique_lengths = set(lengths.values())
    if len(unique_lengths) != 1:
        raise ValueError(f"Aligned market lengths do not match: {lengths}")

    return aligned


def initialize_buy_and_hold(markets: List[dict], frames: Dict[str, pd.DataFrame], initial_cash: float):
    cash = initial_cash
    qtys = {}

    for market in markets:
        market_key = market["market_key"]
        first_price = safe_float(frames[market_key].iloc[0]["close"], 0.0)
        target_alloc_pct = market["target_alloc_pct"]
        qty = compute_target_qty(initial_cash, first_price, target_alloc_pct)
        cost = qty * first_price

        if cost > cash:
            affordable_qty = round_down(cash / first_price, get_qty_decimals()) if first_price > 0 else 0.0
            qty = max(affordable_qty, 0.0)
            cost = qty * first_price

        cash -= cost
        qtys[market_key] = qty

    return cash, qtys


def backtest_multi_coin_vwap_strategy() -> pd.DataFrame:
    markets = [normalize_market(market) for market in get_markets()]
    initial_cash = get_initial_cash()
    stop_loss_pct = get_stop_loss_pct()
    min_qty = get_min_qty()
    qty_decimals = get_qty_decimals()
    top_up_threshold_ratio = get_top_up_threshold_ratio()
    interval = get_interval()
    signal_kwargs = get_signal_kwargs()

    total_target_alloc = sum(market["target_alloc_pct"] for market in markets)
    if total_target_alloc > 1.0 + 1e-9:
        raise ValueError(
            f"Sum of target_alloc_pct across MARKETS is {total_target_alloc:.4f}, which is above 1.0."
        )

    quote_coins = {market["quote_coin"] for market in markets}
    if len(quote_coins) > 1:
        raise ValueError("This backtest assumes all configured markets share the same quote coin.")

    frames = load_market_frames(markets, signal_kwargs)
    frames = align_market_frames(frames)

    n_rows = len(next(iter(frames.values())))
    if n_rows == 0:
        raise ValueError("No aligned rows available for backtesting.")

    market_states = {
        market["market_key"]: {
            "base_qty": 0.0,
            "entry_price": None,
            "stop_loss_price": None,
            "prev_signal": 0,
        }
        for market in markets
    }

    bh_cash, bh_qtys = initialize_buy_and_hold(markets, frames, initial_cash)

    cash = initial_cash
    prev_equity = initial_cash
    portfolio_rows = []

    for i in range(n_rows):
        time_key = next(iter(frames.values())).iloc[i]["time_key"]
        current_prices = {
            market["market_key"]: safe_float(frames[market["market_key"]].iloc[i]["close"], 0.0)
            for market in markets
        }

        row_out = {
            "time_key": time_key,
        }

        for market in markets:
            market_key = market["market_key"]
            base_coin = market["base_coin"]
            row = frames[market_key].iloc[i]
            close_price = safe_float(row["close"], 0.0)
            latest_signal = int(safe_float(row.get("signal", 0), 0))
            state = market_states[market_key]

            base_qty = safe_float(state["base_qty"], 0.0)
            entry_price = state["entry_price"]
            stop_loss_price = state["stop_loss_price"]
            prev_signal = int(state["prev_signal"])
            target_alloc_pct = market["target_alloc_pct"]

            position_before_trade = 1 if base_qty >= min_qty else 0
            trade_action = ""
            exit_reason = ""
            target_qty = 0.0
            traded_this_bar = False

            if position_before_trade == 1:
                stop_hit = (
                    stop_loss_price is not None
                    and stop_loss_pct > 0
                    and close_price > 0
                    and close_price <= stop_loss_price
                )
                signal_exit = prev_signal == 1 and latest_signal == 0

                if stop_hit or signal_exit:
                    sell_qty = compute_exit_qty(base_qty)
                    if sell_qty > 0:
                        cash += sell_qty * close_price
                        base_qty -= sell_qty

                        if base_qty < min_qty:
                            if base_qty > 0:
                                cash += base_qty * close_price
                            base_qty = 0.0

                        entry_price = None
                        stop_loss_price = None
                        trade_action = "SELL"
                        exit_reason = "stop_loss" if stop_hit else "signal_exit"
                        traded_this_bar = True

            total_equity_now = compute_total_equity(
                cash=cash,
                market_states={
                    **market_states,
                    market_key: {
                        **market_states[market_key],
                        "base_qty": base_qty,
                    },
                },
                current_prices=current_prices,
            )
            target_qty = compute_target_qty(total_equity_now, close_price, target_alloc_pct)

            if not traded_this_bar and latest_signal == 1 and close_price > 0:
                if base_qty < min_qty:
                    buy_qty = target_qty
                    buy_cost = buy_qty * close_price

                    if buy_qty >= min_qty and buy_cost <= cash:
                        cash -= buy_cost
                        base_qty = buy_qty
                        entry_price = close_price
                        stop_loss_price = close_price * (1 - stop_loss_pct) if stop_loss_pct > 0 else None
                        trade_action = "BUY"
                else:
                    gap_qty = round_down(max(target_qty - base_qty, 0.0), qty_decimals)
                    needs_top_up = target_qty > 0 and base_qty < target_qty * top_up_threshold_ratio
                    buy_cost = gap_qty * close_price

                    if needs_top_up and gap_qty >= min_qty and buy_cost <= cash:
                        old_base_qty = base_qty
                        old_entry_price = entry_price if entry_price is not None else close_price

                        cash -= buy_cost
                        base_qty += gap_qty

                        total_qty = old_base_qty + gap_qty
                        if total_qty > 0:
                            entry_price = (
                                (old_base_qty * old_entry_price) + (gap_qty * close_price)
                            ) / total_qty
                        else:
                            entry_price = close_price

                        stop_loss_price = entry_price * (1 - stop_loss_pct) if stop_loss_pct > 0 else None
                        trade_action = "BUY_TOPUP"

            position_after_trade = 1 if base_qty >= min_qty else 0

            market_states[market_key] = {
                "base_qty": base_qty,
                "entry_price": entry_price,
                "stop_loss_price": stop_loss_price,
                "prev_signal": latest_signal,
            }

            row_out[f"{base_coin}_close"] = close_price
            row_out[f"{base_coin}_signal"] = latest_signal
            row_out[f"{base_coin}_position_before_trade"] = position_before_trade
            row_out[f"{base_coin}_position"] = position_after_trade
            row_out[f"{base_coin}_base_qty"] = base_qty
            row_out[f"{base_coin}_entry_price"] = entry_price if entry_price is not None else np.nan
            row_out[f"{base_coin}_stop_loss_price"] = stop_loss_price if stop_loss_price is not None else np.nan
            row_out[f"{base_coin}_target_qty"] = target_qty
            row_out[f"{base_coin}_trade_action"] = trade_action
            row_out[f"{base_coin}_exit_reason"] = exit_reason
            row_out[f"{base_coin}_vwap"] = safe_float(row.get("vwap"), np.nan)
            row_out[f"{base_coin}_lower_band"] = safe_float(row.get("lower_band"), np.nan)
            row_out[f"{base_coin}_upper_band"] = safe_float(row.get("upper_band"), np.nan)
            row_out[f"{base_coin}_strong_upper_band"] = safe_float(row.get("strong_upper_band"), np.nan)

        portfolio_equity = compute_total_equity(cash, market_states, current_prices)
        portfolio_return = 0.0 if prev_equity <= 0 else (portfolio_equity / prev_equity) - 1

        buy_and_hold_equity = bh_cash
        for market in markets:
            market_key = market["market_key"]
            buy_and_hold_equity += bh_qtys[market_key] * current_prices[market_key]

        row_out["cash"] = cash
        row_out["strategy_equity"] = portfolio_equity
        row_out["strategy_return"] = portfolio_return
        row_out["buy_and_hold_equity"] = buy_and_hold_equity

        portfolio_rows.append(row_out)
        prev_equity = portfolio_equity

    portfolio_df = pd.DataFrame(portfolio_rows)

    strategy_total_return = portfolio_df["strategy_equity"].iloc[-1] / initial_cash - 1
    bh_total_return = portfolio_df["buy_and_hold_equity"].iloc[-1] / initial_cash - 1
    periods_per_year = get_periods_per_year(interval)

    strategy_metrics = compute_metrics(
        portfolio_df["strategy_return"],
        portfolio_df["strategy_equity"],
        periods_per_year=periods_per_year,
    )
    bh_returns = portfolio_df["buy_and_hold_equity"].pct_change().fillna(0.0)
    bh_metrics = compute_metrics(
        bh_returns,
        portfolio_df["buy_and_hold_equity"],
        periods_per_year=periods_per_year,
    )

    overall_actions = pd.Series("", index=portfolio_df.index)
    overall_exit_reasons = pd.Series("", index=portfolio_df.index)
    for market in markets:
        base_coin = market["base_coin"]
        actions = portfolio_df[f"{base_coin}_trade_action"].fillna("")
        exits = portfolio_df[f"{base_coin}_exit_reason"].fillna("")
        overall_actions = overall_actions.mask(actions != "", actions)
        overall_exit_reasons = overall_exit_reasons.mask(exits != "", exits)

    overall_trade_stats = compute_trade_stats(
        overall_actions,
        overall_exit_reasons,
        portfolio_df["time_key"],
    )
    overall_trade_stats["total_orders"] = int(
        sum((portfolio_df[f"{market['base_coin']}_trade_action"] != "").sum() for market in markets)
    )
    overall_trade_stats["entries"] = int(
        sum((portfolio_df[f"{market['base_coin']}_trade_action"] == "BUY").sum() for market in markets)
    )
    overall_trade_stats["top_up_buys"] = int(
        sum((portfolio_df[f"{market['base_coin']}_trade_action"] == "BUY_TOPUP").sum() for market in markets)
    )
    overall_trade_stats["exits"] = int(
        sum((portfolio_df[f"{market['base_coin']}_trade_action"] == "SELL").sum() for market in markets)
    )
    overall_trade_stats["stop_loss_exits"] = int(
        sum((portfolio_df[f"{market['base_coin']}_exit_reason"] == "stop_loss").sum() for market in markets)
    )
    overall_trade_stats["signal_exits"] = int(
        sum((portfolio_df[f"{market['base_coin']}_exit_reason"] == "signal_exit").sum() for market in markets)
    )
    overall_trade_stats["round_trips"] = min(
        overall_trade_stats["entries"], overall_trade_stats["exits"]
    )
    overall_trade_stats["orders_per_day_all"] = (
        overall_trade_stats["total_orders"] / overall_trade_stats["sample_days"]
        if overall_trade_stats["sample_days"] > 0
        else 0.0
    )
    overall_trade_stats["orders_per_active_day"] = (
        overall_trade_stats["total_orders"] / overall_trade_stats["active_days"]
        if overall_trade_stats["active_days"] > 0
        else 0.0
    )

    print(f"Backtest interval:      {interval}")
    print(f"Markets:                {', '.join(market['roostoo_pair'] for market in markets)}")
    print(f"Bars loaded:            {len(portfolio_df)}")
    print(f"Sample days:            {overall_trade_stats['sample_days']:.2f}")
    print(f"Initial cash:           {initial_cash:,.2f}")
    print(f"Total target alloc:     {total_target_alloc:.2%}")
    print(f"Stop loss pct:          {stop_loss_pct:.2%}")
    print(f"Top-up threshold:       {top_up_threshold_ratio:.2%}")
    print()

    print(f"Strategy total return:  {strategy_total_return:.2%}")
    print(f"Buy and hold return:    {bh_total_return:.2%}")
    print()

    print("Overall trade frequency")
    print(f"Entries:                {overall_trade_stats['entries']}")
    print(f"Top-up buys:            {overall_trade_stats['top_up_buys']}")
    print(f"Exits:                  {overall_trade_stats['exits']}")
    print(f"Stop-loss exits:        {overall_trade_stats['stop_loss_exits']}")
    print(f"Signal exits:           {overall_trade_stats['signal_exits']}")
    print(f"Total orders:           {overall_trade_stats['total_orders']}")
    print(f"Completed round trips:  {overall_trade_stats['round_trips']}")
    print(f"Active trading days:    {overall_trade_stats['active_days']}")
    print(f"Orders / day:           {overall_trade_stats['orders_per_day_all']:.2f}")
    print(f"Orders / active day:    {overall_trade_stats['orders_per_active_day']:.2f}")
    print()

    print("Strategy metrics")
    print(f"Sharpe Ratio:           {strategy_metrics['sharpe']:.4f}")
    print(f"Sortino Ratio:          {strategy_metrics['sortino']:.4f}")
    print(f"Calmar Ratio:           {strategy_metrics['calmar']:.4f}")
    print(f"Composite Score:        {strategy_metrics['composite']:.4f}")
    print(f"Max Drawdown:           {strategy_metrics['max_drawdown']:.2%}")
    print(f"Annual Return:          {strategy_metrics['annual_return']:.2%}")
    print()

    print("Buy-and-hold metrics")
    print(f"Sharpe Ratio:           {bh_metrics['sharpe']:.4f}")
    print(f"Sortino Ratio:          {bh_metrics['sortino']:.4f}")
    print(f"Calmar Ratio:           {bh_metrics['calmar']:.4f}")
    print(f"Composite Score:        {bh_metrics['composite']:.4f}")
    print(f"Max Drawdown:           {bh_metrics['max_drawdown']:.2%}")
    print(f"Annual Return:          {bh_metrics['annual_return']:.2%}")
    print()

    print("Per-market trade stats")
    for market in markets:
        base_coin = market["base_coin"]
        stats = compute_trade_stats(
            portfolio_df[f"{base_coin}_trade_action"],
            portfolio_df[f"{base_coin}_exit_reason"],
            portfolio_df["time_key"],
        )
        print(f"{market['roostoo_pair']} | alloc={market['target_alloc_pct']:.2%} | "
              f"entries={stats['entries']} | topups={stats['top_up_buys']} | exits={stats['exits']} | "
              f"stoploss={stats['stop_loss_exits']} | signal_exits={stats['signal_exits']}")

    return portfolio_df


if __name__ == "__main__":
    df_result = backtest_multi_coin_vwap_strategy()
