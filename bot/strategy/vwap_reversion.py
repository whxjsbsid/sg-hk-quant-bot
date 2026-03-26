# bot/strategies/vwap_reversion.py

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def _validate_inputs(df: pd.DataFrame, window: int, trend_window: int) -> None:
    if window <= 0:
        raise ValueError("window must be greater than 0")
    if trend_window <= 0:
        raise ValueError("trend_window must be greater than 0")

    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")


def generate_vwap_signal(
    df: pd.DataFrame,
    window: int,
    lower_std_mult: float,
    exit_std_mult: float,
    strong_exit_std_mult: float,
    trend_window: int,
) -> pd.DataFrame:
    _validate_inputs(df, window, trend_window)

    signal_df = df.copy()

    if "open_time" in signal_df.columns:
        signal_df = signal_df.sort_values("open_time").reset_index(drop=True)

    signal_df["typical_price"] = (
        signal_df["high"] + signal_df["low"] + signal_df["close"]
    ) / 3

    price_volume = signal_df["typical_price"] * signal_df["volume"]
    rolling_price_volume = price_volume.rolling(window=window, min_periods=window).sum()
    rolling_volume = signal_df["volume"].rolling(window=window, min_periods=window).sum()

    signal_df["vwap"] = rolling_price_volume / rolling_volume.replace(0, np.nan)
    signal_df["std"] = signal_df["close"].rolling(window=window, min_periods=window).std()

    signal_df["trend_sma"] = signal_df["close"].rolling(
        window=trend_window,
        min_periods=trend_window,
    ).mean()
    signal_df["uptrend"] = signal_df["close"] > signal_df["trend_sma"]

    signal_df["lower_band"] = signal_df["vwap"] - lower_std_mult * signal_df["std"]
    signal_df["upper_band"] = signal_df["vwap"] + exit_std_mult * signal_df["std"]
    signal_df["strong_upper_band"] = (
        signal_df["vwap"] + strong_exit_std_mult * signal_df["std"]
    )

    entry_mask = signal_df["close"] < signal_df["lower_band"]
    exit_mask = (
        (signal_df["uptrend"] & (signal_df["close"] > signal_df["strong_upper_band"]))
        | (~signal_df["uptrend"] & (signal_df["close"] > signal_df["upper_band"]))
    )

    signal_df["signal"] = np.nan
    signal_df.loc[entry_mask, "signal"] = 1
    signal_df.loc[exit_mask, "signal"] = 0
    signal_df["signal"] = signal_df["signal"].ffill().fillna(0).astype(int)

    return signal_df
