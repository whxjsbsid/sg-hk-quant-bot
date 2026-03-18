import pandas as pd

from bot.data.binance_loader import load_binance_klines
from bot.strategy.vwap_reversion import generate_vwap_signal


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

    total_return = df["strategy_equity"].iloc[-1] / initial_cash - 1
    bh_return = df["buy_and_hold_equity"].iloc[-1] / initial_cash - 1

    print(f"Strategy total return: {total_return:.2%}")
    print(f"Buy and hold return:   {bh_return:.2%}")
    print(df[["open_time", "close", "vwap", "signal", "position", "strategy_equity"]].tail(10))

    return df


if __name__ == "__main__":
    df_result = backtest_vwap_strategy(
        symbol="BTCUSDT",
        interval="1d",
        limit=500,
        window=20,
    )
