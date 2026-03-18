import pandas as pd
import numpy as np


def generate_vwap_signal(
    df: pd.DataFrame,
    window: int = 20,
    lower_std_mult: float = 0.75,
    strong_exit_std_mult: float = 2,
    trend_window: int = 100,
) -> pd.DataFrame:
    """
    Long-only VWAP mean reversion with trend-aware exit.

    Entry:
        buy when close < vwap - lower_std_mult * std

    Exit:
        if close > SMA(trend_window), use wider exit:
            close > vwap + strong_exit_std_mult * std
        else use tighter exit:
            close > vwap

    Expects columns: open, high, low, close, volume
    """
    df = df.copy()

    # Typical price for rolling VWAP
    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3

    pv = df["typical_price"] * df["volume"]
    df["vwap"] = (
        pv.rolling(window=window, min_periods=window).sum()
        / df["volume"].rolling(window=window, min_periods=window).sum()
    )

    # Rolling std of close
    df["std"] = df["close"].rolling(window=window, min_periods=window).std()

    # Trend filter
    df["sma100"] = df["close"].rolling(window=trend_window, min_periods=trend_window).mean()
    df["uptrend"] = df["close"] > df["sma100"]

    # Bands
    df["lower_band"] = df["vwap"] - lower_std_mult * df["std"]
    df["strong_upper_band"] = df["vwap"] + strong_exit_std_mult * df["std"]

    # Rules
    entry = df["close"] < df["lower_band"]

    exit_cond = (
        (df["uptrend"] & (df["close"] > df["strong_upper_band"])) |
        (~df["uptrend"] & (df["close"] > df["vwap"]))
    )

    # Stateful signal: 1 = long, 0 = flat
    df["signal"] = np.nan
    df.loc[entry, "signal"] = 1
    df.loc[exit_cond, "signal"] = 0
    df["signal"] = df["signal"].ffill().fillna(0)

    return df
