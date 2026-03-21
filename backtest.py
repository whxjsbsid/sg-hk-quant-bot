import pandas as pd
import numpy as np

from bot.data.binance_loader import load_binance_klines
from bot.strategy.vwap_reversion import generate_vwap_signal
from bot.config import settings


def get_periods_per_year(interval: str) -> int:
    mapping = {
        "1d": 365,
        "1h": 24 * 365,
        "15m": 4 * 24 * 365,
        "5m": 12 * 24 * 365,
        "1m": 60 * 24 * 365,
    }
    return mapping.get(interval, 365)


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

    out["position_change"] = out["position"].diff().fillna(out["position"])
    out["entry"] = out["position_change"] > 0
    out["exit"] = out["position_change"] < 0
    out["trade_event"] = out["entry"] | out["exit"]

    entries = int(out["entry"].sum())
    exits = int(out["exit"].sum())
    total_orders = entries + exits
    round_trips = min(entries, exits)

    if "open_time" in out.columns:
        out["trade_date"] = pd.to_datetime(out["open_time"]).dt.date
    else:
        out["trade_date"] = pd.RangeIndex(len(out))

    active_days = int(out.loc[out["trade_event"], "trade_date"].nunique()) if total_orders > 0 else 0

    if len(out) > 0 and "open_time" in out.columns:
        start_ts = pd.to_datetime(out["open_time"].iloc[0])
        end_ts = pd.to_datetime(out["open_time"].iloc[-1])
        sample_days = max((end_ts - start_ts).total_seconds() / 86400, 1e-9)
    else:
        sample_days = 0.0

    orders_per_day_all = total_orders / sample_days if sample_days > 0 else 0.0
    orders_per_active_day = total_orders / active_days if active_days > 0 else 0.0

    return {
        "entries": entries,
        "exits": exits,
        "total_orders": total_orders,
        "round_trips": round_trips,
        "active_days": active_days,
        "orders_per_day_all": orders_per_day_all,
        "orders_per_active_day": orders_per_active_day,
        "sample_days": sample_days,
    }


def backtest_vwap_strategy(
    symbol: str,
    interval: str,
    limit: int,
    window: int,
    initial_cash: float,
    lower_std_mult: float,
    strong_exit_std_mult: float,
    trend_window: int,
) -> pd.DataFrame:
    df = load_binance_klines(symbol=symbol, interval=interval, limit=limit)

    df = generate_vwap_signal(
        df,
        window=window,
        lower_std_mult=lower_std_mult,
        strong_exit_std_mult=strong_exit_std_mult,
        trend_window=trend_window,
    )

    df["position"] = df["signal"].shift(1).fillna(0).astype(int)
    df["return"] = df["close"].pct_change().fillna(0)
    df["strategy_return"] = df["position"] * df["return"]

    df["buy_and_hold_equity"] = initial_cash * (1 + df["return"]).cumprod()
    df["strategy_equity"] = initial_cash * (1 + df["strategy_return"]).cumprod()

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
    print()
    print(f"Strategy total return:  {strategy_total_return:.2%}")
    print(f"Buy and hold return:    {bh_total_return:.2%}")
    print()

    print("Trade frequency")
    print(f"Entries:                {trade_stats['entries']}")
    print(f"Exits:                  {trade_stats['exits']}")
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
        strong_exit_std_mult=settings.STRONG_EXIT_STD_MULT,
        trend_window=settings.TREND_WINDOW,
    )
