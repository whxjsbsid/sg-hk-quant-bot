import math

import numpy as np
import pandas as pd

from bot.config import settings
from bot.data.binance_loader import load_binance_klines
from bot.strategy.vwap_reversion import generate_vwap_signal


def safe_float(value, default: float = 0.0) -> float:
    try:
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


def get_target_alloc_pct() -> float:
    pct = safe_float(getattr(settings, "TARGET_ALLOC_PCT", 1.0), 1.0)
    return min(max(pct, 0.0), 1.0)


def get_stop_loss_pct() -> float:
    pct = safe_float(getattr(settings, "STOP_LOSS_PCT", 0.0), 0.0)
    return max(pct, 0.0)


def get_min_qty() -> float:
    return max(safe_float(getattr(settings, "MIN_QTY", 0.0), 0.0), 0.0)


def get_qty_decimals() -> int:
    try:
        return max(int(getattr(settings, "QTY_DECIMALS", 8)), 0)
    except (TypeError, ValueError):
        return 8


def get_sell_buffer_ratio() -> float:
    ratio = safe_float(getattr(settings, "SELL_BUFFER_RATIO", 1.0), 1.0)
    return min(max(ratio, 0.0), 1.0)


def get_close_full_position_on_exit() -> bool:
    value = getattr(settings, "CLOSE_FULL_POSITION_ON_EXIT", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


def get_top_up_threshold_ratio() -> float:
    ratio = safe_float(getattr(settings, "TOP_UP_THRESHOLD_RATIO", 0.95), 0.95)
    return min(max(ratio, 0.0), 1.0)


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


def compute_trade_stats(df: pd.DataFrame) -> dict:
    out = df.copy()

    if "trade_action" in out.columns:
        buy_entries = int((out["trade_action"] == "BUY").sum())
        top_up_buys = int((out["trade_action"] == "BUY_TOPUP").sum())
        sell_orders = int((out["trade_action"] == "SELL").sum())
        total_orders = buy_entries + top_up_buys + sell_orders
        round_trips = min(buy_entries, sell_orders)
        trade_event_mask = out["trade_action"] != ""
    else:
        buy_entries = 0
        top_up_buys = 0
        sell_orders = 0
        total_orders = 0
        round_trips = 0
        trade_event_mask = pd.Series(False, index=out.index)

    stop_loss_exits = 0
    signal_exits = 0
    if "exit_reason" in out.columns:
        stop_loss_exits = int((out["exit_reason"] == "stop_loss").sum())
        signal_exits = int((out["exit_reason"] == "signal_exit").sum())

    if len(out) > 0 and "open_time" in out.columns:
        out["trade_date"] = pd.to_datetime(out["open_time"]).dt.date
    else:
        out["trade_date"] = pd.RangeIndex(len(out))

    active_days = int(out.loc[trade_event_mask, "trade_date"].nunique()) if total_orders > 0 else 0

    if len(out) > 0 and "open_time" in out.columns:
        start_ts = pd.to_datetime(out["open_time"].iloc[0])
        end_ts = pd.to_datetime(out["open_time"].iloc[-1])
        sample_days = max((end_ts - start_ts).total_seconds() / 86400, 1e-9)
    else:
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


def compute_target_qty(total_equity: float, close_price: float) -> float:
    target_alloc_pct = get_target_alloc_pct()
    qty_decimals = get_qty_decimals()

    if close_price <= 0:
        return 0.0

    target_notional = total_equity * target_alloc_pct
    raw_qty = target_notional / close_price
    return round_down(raw_qty, qty_decimals)


def compute_exit_qty(base_qty: float) -> float:
    qty_decimals = get_qty_decimals()
    sell_buffer_ratio = get_sell_buffer_ratio()
    close_full_position_on_exit = get_close_full_position_on_exit()

    if close_full_position_on_exit:
        qty = round_down(base_qty, qty_decimals)
    else:
        qty = round_down(base_qty * sell_buffer_ratio, qty_decimals)

    if qty <= 0:
        qty = round_down(base_qty, qty_decimals)

    return min(qty, base_qty)


def backtest_vwap_strategy(
    symbol: str,
    interval: str,
    limit: int,
    window: int,
    initial_cash: float,
    lower_std_mult: float,
    exit_std_mult: float,
    strong_exit_std_mult: float,
    trend_window: int,
) -> pd.DataFrame:
    df = load_binance_klines(symbol=symbol, interval=interval, limit=limit)

    df = generate_vwap_signal(
        df,
        window=window,
        lower_std_mult=lower_std_mult,
        exit_std_mult=exit_std_mult,
        strong_exit_std_mult=strong_exit_std_mult,
        trend_window=trend_window,
    ).copy()

    target_alloc_pct = get_target_alloc_pct()
    stop_loss_pct = get_stop_loss_pct()
    min_qty = get_min_qty()
    qty_decimals = get_qty_decimals()
    top_up_threshold_ratio = get_top_up_threshold_ratio()

    df["return"] = df["close"].pct_change().fillna(0.0)
    df["buy_and_hold_equity"] = initial_cash * (1 + df["return"]).cumprod()

    cash = safe_float(initial_cash, 0.0)
    base_qty = 0.0
    entry_price = None
    stop_loss_price = None
    prev_equity = cash

    strategy_returns = []
    strategy_equity = []
    positions_before_trade = []
    positions_after_trade = []
    cash_series = []
    base_qty_series = []
    entry_price_series = []
    stop_loss_price_series = []
    trade_actions = []
    exit_reasons = []
    target_qty_series = []

    prev_signal = 0

    for _, row in df.iterrows():
        close_price = safe_float(row["close"], 0.0)
        latest_signal = int(safe_float(row.get("signal", 0), 0))

        position_before_trade = 1 if base_qty >= min_qty else 0
        equity_before_trade = cash + (base_qty * close_price)
        strategy_return = 0.0 if prev_equity <= 0 else (equity_before_trade / prev_equity) - 1

        trade_action = ""
        exit_reason = ""
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

        current_target_qty = 0.0
        if close_price > 0:
            total_equity = cash + (base_qty * close_price)
            current_target_qty = compute_target_qty(total_equity, close_price)

        if not traded_this_bar and latest_signal == 1 and close_price > 0:
            if base_qty < min_qty:
                buy_qty = current_target_qty
                buy_cost = buy_qty * close_price

                if buy_qty >= min_qty and buy_cost <= cash:
                    cash -= buy_cost
                    base_qty = buy_qty
                    entry_price = close_price
                    stop_loss_price = close_price * (1 - stop_loss_pct) if stop_loss_pct > 0 else None
                    trade_action = "BUY"
            else:
                gap_qty = round_down(max(current_target_qty - base_qty, 0.0), qty_decimals)
                needs_top_up = (
                    current_target_qty > 0
                    and base_qty < current_target_qty * top_up_threshold_ratio
                )
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
        equity_after_trade = cash + (base_qty * close_price)

        strategy_returns.append(strategy_return)
        strategy_equity.append(equity_after_trade)
        positions_before_trade.append(position_before_trade)
        positions_after_trade.append(position_after_trade)
        cash_series.append(cash)
        base_qty_series.append(base_qty)
        entry_price_series.append(entry_price if entry_price is not None else np.nan)
        stop_loss_price_series.append(stop_loss_price if stop_loss_price is not None else np.nan)
        trade_actions.append(trade_action)
        exit_reasons.append(exit_reason)
        target_qty_series.append(current_target_qty)

        prev_equity = equity_after_trade
        prev_signal = latest_signal

    df["position_before_trade"] = positions_before_trade
    df["position"] = positions_after_trade
    df["cash"] = cash_series
    df["base_qty"] = base_qty_series
    df["entry_price"] = entry_price_series
    df["stop_loss_price"] = stop_loss_price_series
    df["target_qty"] = target_qty_series
    df["trade_action"] = trade_actions
    df["exit_reason"] = exit_reasons
    df["strategy_return"] = pd.Series(strategy_returns, index=df.index)
    df["strategy_equity"] = pd.Series(strategy_equity, index=df.index)

    strategy_total_return = df["strategy_equity"].iloc[-1] / initial_cash - 1
    bh_total_return = df["buy_and_hold_equity"].iloc[-1] / initial_cash - 1

    periods_per_year = get_periods_per_year(interval)

    strategy_metrics = compute_metrics(
        df["strategy_return"],
        df["strategy_equity"],
        periods_per_year=periods_per_year,
    )
    bh_metrics = compute_metrics(
        df["return"],
        df["buy_and_hold_equity"],
        periods_per_year=periods_per_year,
    )

    trade_stats = compute_trade_stats(df)

    print(f"Backtest interval:      {interval}")
    print(f"Bars loaded:            {len(df)}")
    print(f"Sample days:            {trade_stats['sample_days']:.2f}")
    print(f"Target allocation:      {target_alloc_pct:.2%}")
    print(f"Stop loss pct:          {stop_loss_pct:.2%}")
    print(f"Top-up threshold:       {top_up_threshold_ratio:.2%}")
    print()

    print(f"Strategy total return:  {strategy_total_return:.2%}")
    print(f"Buy and hold return:    {bh_total_return:.2%}")
    print()

    print("Trade frequency")
    print(f"Entries:                {trade_stats['entries']}")
    print(f"Top-up buys:            {trade_stats['top_up_buys']}")
    print(f"Exits:                  {trade_stats['exits']}")
    print(f"Stop-loss exits:        {trade_stats['stop_loss_exits']}")
    print(f"Signal exits:           {trade_stats['signal_exits']}")
    print(f"Total orders:           {trade_stats['total_orders']}")
    print(f"Completed round trips:  {trade_stats['round_trips']}")
    print(f"Active trading days:    {trade_stats['active_days']}")
    print(f"Orders / day:           {trade_stats['orders_per_day_all']:.2f}")
    print(f"Orders / active day:    {trade_stats['orders_per_active_day']:.2f}")
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

    return df


if __name__ == "__main__":
    df_result = backtest_vwap_strategy(
        symbol=settings.BINANCE_SYMBOL,
        interval=settings.INTERVAL,
        limit=settings.LIMIT,
        window=settings.VWAP_WINDOW,
        initial_cash=settings.INITIAL_CASH,
        lower_std_mult=settings.LOWER_STD_MULT,
        exit_std_mult=settings.EXIT_STD_MULT,
        strong_exit_std_mult=settings.STRONG_EXIT_STD_MULT,
        trend_window=settings.TREND_WINDOW,
    )
