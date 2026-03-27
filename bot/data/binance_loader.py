# bot/data/binance_loader.py

import re
from typing import Any, List, Optional, Set

import pandas as pd
import requests


BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_MAX_LIMIT = 1000
REQUEST_TIMEOUT = 10

KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
    "ignore",
]

NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_asset_volume",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
]


def interval_to_milliseconds(interval: str) -> int:
    match = re.fullmatch(r"(\d+)([mhdwM])", interval)
    if not match:
        raise ValueError(f"Unsupported interval format: {interval}")

    value, unit = match.groups()
    unit_ms = {
        "m": 60 * 1000,
        "h": 60 * 60 * 60 * 1000 // 60,
        "d": 24 * 60 * 60 * 1000,
        "w": 7 * 24 * 60 * 60 * 1000,
        "M": 30 * 24 * 60 * 60 * 1000,
    }
    return int(value) * unit_ms[unit]


def _fetch_klines_batch(
    symbol: str,
    interval: str,
    limit: int,
    end_time: Optional[int] = None,
) -> List[List[Any]]:
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    if end_time is not None:
        params["endTime"] = end_time

    try:
        response = requests.get(
            BINANCE_KLINES_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Failed to fetch Binance klines for {symbol} ({interval})."
        ) from exc

    return response.json()


def _to_dataframe(rows: List[List[Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=KLINE_COLUMNS)

    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["number_of_trades"] = pd.to_numeric(
        df["number_of_trades"],
        errors="coerce",
    ).astype("Int64")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

    return df.reset_index(drop=True)


def load_binance_klines(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    limit: int = 500,
) -> pd.DataFrame:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")

    all_rows: List[List[Any]] = []
    seen_open_times: Set[int] = set()
    end_time: Optional[int] = None

    while len(all_rows) < limit:
        batch_limit = min(limit - len(all_rows), BINANCE_MAX_LIMIT)
        rows = _fetch_klines_batch(
            symbol=symbol,
            interval=interval,
            limit=batch_limit,
            end_time=end_time,
        )

        if not rows:
            break

        unique_rows = []
        for row in rows:
            open_time = row[0]
            if open_time not in seen_open_times:
                seen_open_times.add(open_time)
                unique_rows.append(row)

        if not unique_rows:
            break

        all_rows.extend(unique_rows)
        end_time = unique_rows[0][0] - 1

        if len(rows) < batch_limit:
            break

    if not all_rows:
        raise ValueError(f"No kline data returned from Binance for {symbol}.")

    all_rows = sorted(all_rows, key=lambda row: row[0])[-limit:]
    return _to_dataframe(all_rows)
