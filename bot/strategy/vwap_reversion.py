import pandas as pd
import numpy as np


def generate_vwap_signal(
    df: pd.DataFrame,
    window: int = 20,
    lower_std_mult: float = 0.75,
    strong_exit_std_mult: float = 2.0,
    trend_window: int = 100,
) -> pd.DataFrame:
    df = df.copy()

    required_cols = ["open", "high", "low", "close", "volume"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3

    pv = df["typical_price"] * df["volume"]
    rolling_pv = pv.rolling(window=window, min_periods=window).sum()
    rolling_vol = df["volume"].rolling(window=window, min_periods=window).sum()

    df["vwap"] = rolling_pv / rolling_vol.replace(0, np.nan)
    df["std"] = df["close"].rolling(window=window, min_periods=window).std()

    df["trend_sma"] = df["close"].rolling(
        window=trend_window,
        min_periods=trend_window
    ).mean()
    df["uptrend"] = df["close"] > df["trend_sma"]

    df["lower_band"] = df["vwap"] - lower_std_mult * df["std"]
    df["strong_upper_band"] = df["vwap"] + strong_exit_std_mult * df["std"]

    entry = df["close"] < df["lower_band"]
    exit_cond = (
        (df["uptrend"] & (df["close"] > df["strong_upper_band"])) |
        (~df["uptrend"] & (df["close"] > df["vwap"]))
    )

    df["signal"] = np.nan
    df.loc[entry, "signal"] = 1
    df.loc[exit_cond, "signal"] = 0
    df["signal"] = df["signal"].ffill().fillna(0).astype(int)

    return df
