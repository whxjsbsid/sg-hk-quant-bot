import pandas as pd
import numpy as np

from bot.data.binance_loader import load_binance_klines
from bot.strategy.vwap_reversion import generate_vwap_signal


def compute_metrics(return_series: pd.Series, equity_series: pd.Series, periods_per_year: int = 365):
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

    # Sharpe Ratio
    mean_return = r.mean()
    std_return = r.std(ddof=0)
    sharpe = 0.0 if std_return == 0 else (mean_return / std_return) * np.sqrt(periods_per_year)

    # Sortino Ratio
    downside = r[r < 0]
    downside_std = downside.std(ddof=0)
    sortino = 0.0 if downside_std == 0 or np.isnan(downside_std) else (mean_return / downside_std) * np.sqrt(periods_per_year)

    # Max Drawdown
    rolling_max = equity_series.cummax()
    drawdown = (equity_series - rolling_max) / rolling_max
    max_drawdown = abs(drawdown.min()) if len(drawdown) > 0 else 0.0

    # Annual Return
    total_return = equity_series.iloc[-1] / equity_series.iloc[0] - 1
    n_periods = len(r)
    annual_return = (1 + total_return) ** (periods_per_year / n_periods) - 1 if n_periods > 0 else 0.0

    # Calmar Ratio
    calmar = 0.0 if max_drawdown == 0 else annual_return / max_drawdown

    # Composite Score
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
    interval: str = "1d",
    limit: int = 500,
    window: int = 20,
    initial_cash: float = 10000,
) -> pd.DataFrame:
    df = load_binance_klines(symbol=symbol, interval=interval, limit=limit)

    df = generate_vwap_signal(df, window=window)

    # Trade on next candle to avoid lookahead bias
    df["position"] = df["signal"].shift(1).fillna(0)

    # Asset returns
    df["return"] = df["close"].pct_change().fillna(0)

    # Long-only strategy returns
    df["strategy_return"] = df["position"] * df["return"]

    # Equity curves
    df["buy_and_hold_equity"] = initial_cash * (1 + df["return"]).cumprod()
    df["strategy_equity"] = initial_cash * (1 + df["strategy_return"]).cumprod()

    strategy_total_return = df["strategy_equity"].iloc[-1] / initial_cash - 1
    bh_total_return = df["buy_and_hold_equity"].iloc[-1] / initial_cash - 1

    strategy_metrics = compute_metrics(df["strategy_return"], df["strategy_equity"], periods_per_year=365)
    bh_metrics = compute_metrics(df["return"], df["buy_and_hold_equity"], periods_per_year=365)

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
        "lower_band", "upper_band", "signal",
        "position", "strategy_equity"
    ]].tail(10))

    return df


if __name__ == "__main__":
    df_result = backtest_vwap_strategy(
        symbol="BTCUSDT",
        interval="1d",
        limit=500,
        window=20,
    )
