import pandas as pd

from bot.strategy.vwap_reversion import generate_vwap_signal

def backtest_vwap_strategy(csv_path: str, window: int = 20, initial_cash: float = 10000):
    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]

    if "timestamp" in df.columns:
        df = df.sort_values("timestamp")
    elif "date" in df.columns:
        df = df.sort_values("date")

    df = generate_vwap_signal(df, window=window)

    # Trade on next candle to avoid lookahead bias
    df["position"] = df["signal"].shift(1).fillna(0)

    # Asset returns
    df["return"] = df["close"].pct_change().fillna(0)

    # Strategy returns: only earn returns when in long position
    df["strategy_return"] = df["position"] * df["return"]

    # Equity curves
    df["buy_and_hold_equity"] = initial_cash * (1 + df["return"]).cumprod()
    df["strategy_equity"] = initial_cash * (1 + df["strategy_return"]).cumprod()

    total_return = df["strategy_equity"].iloc[-1] / initial_cash - 1
    bh_return = df["buy_and_hold_equity"].iloc[-1] / initial_cash - 1

    print(f"Strategy total return: {total_return:.2%}")
    print(f"Buy and hold return:   {bh_return:.2%}")

    print(df[["close", "vwap", "signal", "position", "strategy_equity"]].tail(10))

    return df

if __name__ == "__main__":
    df_result = backtest_vwap_strategy("bot/data/btcusdt_daily.csv", window=20)
