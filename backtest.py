import pandas as pd
import numpy as np

from bot.data.binance_loader import load_binance_klines
from bot.strategy.vwap_reversion import generate_vwap_signal


def get_periods_per_year(interval: str) -> int:
    mapping = {
        "1d": 365,
        "1h": 24 * 365,
        "15m": 4 * 24 * 365,
        "5m": 12 * 24 * 365,
        "1m": 60 * 24 * 365,
    }
    return mapping.get(interval, 365)


def compute_metrics(return_series: pd.Series, equity_series: pd.Series, periods_per_year: int):
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


def backtest_vwap_strategy(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    limit: int = 500,
    window: int = 20,
    initial_cash: float = 10000,
) -> pd.DataFrame:
    df = load_binance_klines(symbol=symbol, interval=interval, limit=limit)
    df = generate_vwap_signal(df, window=window)

    df["position"] = df["signal"].shift(1).fillna(0)
    df["return"] = df["close"].pct_change().fillna(0)
    df["strategy_return"] = df["position"] * df["return"]

    df["buy_and_hold_equity"] = initial_cash * (1 + df["return"]).cumprod()
    df["strategy_equity"] = initial_cash * (1 + df["strategy_return"]).cumprod()

    strategy_total_return = df["strategy_equity"].iloc[-1] / initial_cash - 1
    bh_total_return = df["buy_and_hold_equity"].iloc[-1] / initial_cash - 1

    periods_per_year = get_periods_per_year(interval)

    strategy_metrics = compute_metrics(df["strategy_return"], df["strategy_equity"], periods_per_year=periods_per_year)
    bh_metrics = compute_metrics(df["return"], df["buy_and_hold_equity"], periods_per_year=periods_per_year)

    print(f"Strategy total return: {strategy_total_return:.2%}")
    print(f"Buy and hold return:   {bh_total_return:.2%}")
    print()

    print("Strategy metrics")
    print(f"Sharpe Ratio:    {strategy_metrics['sharpe']:.4f}")
    print(f"Sortino Ratio:   {strategy_metrics['sortino']:.4f}")
    print(f"Calmar Ratio:    {strategy_metrics['calmar']:.4f}")
    print(f"Composite Score: {strategy_metrics['composite']:.4f}")
    print(f"Max Drawdown:    {strategy_metrics['max_drawdown']:.2%}")
    print(f"Annual Return:   {strategy_metrics['annual_return']:.2%}")
    print()

    print("Buy-and-hold metrics")
    print(f"Sharpe Ratio:    {bh_metrics['sharpe']:.4f}")
    print(f"Sortino Ratio:   {bh_metrics['sortino']:.4f}")
    print(f"Calmar Ratio:    {bh_metrics['calmar']:.4f}")
    print(f"Composite Score: {bh_metrics['composite']:.4f}")
    print(f"Max Drawdown:    {bh_metrics['max_drawdown']:.2%}")
    print(f"Annual Return:   {bh_metrics['annual_return']:.2%}")
    print()

    print(df[[
        "open_time", "close", "vwap", "std",
        "lower_band", "strong_upper_band", "signal",
        "position", "strategy_equity"
    ]].tail(10))

    return df


if __name__ == "__main__":
    df_result = backtest_vwap_strategy(
        symbol="BTCUSDT",
        interval="1h",
        limit=1000,
        window=20,
    )
