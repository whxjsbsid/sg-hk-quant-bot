import pandas as pd
import numpy as np

def generate_vwap_signal(
    df: pd.DataFrame,
    window: int = 20,
    lower_std_mult = 0.75,
    upper_std_mult = 1.9
) -> pd.DataFrame:
    """
    Long-only VWAP band strategy.

    Enter long when close < lower_band
    Exit long when close > upper_band
    Otherwise keep previous state

    Expects columns: open, high, low, close, volume
    """
    df = df.copy()

    # VWAP input price
    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3

    # Rolling VWAP
    pv = df["typical_price"] * df["volume"]
    df["vwap"] = (
        pv.rolling(window=window).sum()
        / df["volume"].rolling(window=window).sum()
    )

    # Rolling standard deviation of close
    df["std"] = df["close"].rolling(window=window).std()

    # Bands
    df["lower_band"] = df["vwap"] - lower_std_mult * df["std"]
    df["upper_band"] = df["vwap"] + upper_std_mult * df["std"]

    # Entry / exit conditions
    entry = df["close"] < df["lower_band"]
    exit_ = df["close"] > df["upper_band"]

    # Desired state:
    # 1 = long
    # 0 = flat
    df["signal"] = np.nan
    df.loc[entry, "signal"] = 1
    df.loc[exit_, "signal"] = 0

    # Hold previous state when neither entry nor exit happens
    df["signal"] = df["signal"].ffill().fillna(0)

    return df
