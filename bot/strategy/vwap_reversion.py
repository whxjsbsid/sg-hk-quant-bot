import pandas as pd
import numpy as np

def generate_vwap_signal(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    Expects columns: open, high, low, close, volume

    Returns df with:
    - typical_price
    - vwap
    - signal
        1 = buy / enter long
        0 = exit / stay out
    """
    df = df.copy()

    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3

    pv = df["typical_price"] * df["volume"]
    df["vwap"] = (
        pv.rolling(window=window).sum()
        / df["volume"].rolling(window=window).sum()
    )

    df["signal"] = np.where(df["close"] < df["vwap"], 1, 0)

    return df
