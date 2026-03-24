import pandas as pd
import numpy as np
from bot.config import settings


def generate_vwap_signal(
    df: pd.DataFrame,
    window: int = None,
    lower_std_mult: float = None,
    exit_std_mult: float = None,
    strong_exit_std_mult: float = None,
    trend_window: int = None,
) -> pd.DataFrame:
    df = df.copy()

    if window is None:
        window = settings.VWAP_WINDOW
    if lower_std_mult is None:
        lower_std_mult = settings.LOWER_STD_MULT
    if exit_std_mult is None:
        exit_std_mult = settings.EXIT_STD_MULT
    if strong_exit_std_mult is None:
        strong_exit_std_mult = settings.STRONG_EXIT_STD_MULT
    if trend_window is None:
        trend_window = settings.TREND_WINDOW

    if window <= 0:
        raise ValueError("window must be greater than 0")
    if trend_window <= 0:
        raise ValueError("trend_window must be greater than 0")

    required_cols = ["open", "high", "low", "close", "volume"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    if "open_time" in df.columns:
        df = df.sort_values("open_time").reset_index(drop=True)

    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3

    pv = df["typical_price"] * df["volume"]
    rolling_pv = pv.rolling(window=window, min_periods=window).sum()
    rolling_vol = df["volume"].rolling(window=window, min_periods=window).sum()

    df["vwap"] = rolling_pv / rolling_vol.replace(0, np.nan)
    df["std"] = df["close"].rolling(window=window, min_periods=window).std()

    df["trend_sma"] = df["close"].rolling(
        window=trend_window,
        min_periods=trend_window,
    ).mean()
    df["uptrend"] = df["close"] > df["trend_sma"]

    df["lower_band"] = df["vwap"] - lower_std_mult * df["std"]
    df["upper_band"] = df["vwap"] + exit_std_mult * df["std"]
    df["strong_upper_band"] = df["vwap"] + strong_exit_std_mult * df["std"]

    entry = df["close"] < df["lower_band"]
    exit_cond = (
        (df["uptrend"] & (df["close"] > df["strong_upper_band"]))
        | (~df["uptrend"] & (df["close"] > df["upper_band"]))
    )

    df["signal"] = np.nan
    df.loc[entry, "signal"] = 1
    df.loc[exit_cond, "signal"] = 0
    df["signal"] = df["signal"].ffill().fillna(0).astype(int)

    return df
