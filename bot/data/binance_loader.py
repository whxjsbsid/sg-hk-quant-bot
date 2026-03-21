import re
import requests
import pandas as pd


BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_MAX_LIMIT = 1000


def interval_to_milliseconds(interval: str) -> int:
    match = re.fullmatch(r"(\d+)([mhdwM])", interval)
    if not match:
        raise ValueError(f"Unsupported interval format: {interval}")

    value = int(match.group(1))
    unit = match.group(2)

    unit_ms = {
        "m": 60 * 1000,
        "h": 60 * 60 * 1000,
        "d": 24 * 60 * 60 * 1000,
        "w": 7 * 24 * 60 * 60 * 1000,
        "M": 30 * 24 * 60 * 60 * 1000,
    }

    return value * unit_ms[unit]


def load_binance_klines(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    limit: int = 500,
) -> pd.DataFrame:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")

    all_rows = []
    seen_open_times = set()
    end_time = None

    while len(all_rows) < limit:
        batch_limit = min(limit - len(all_rows), BINANCE_MAX_LIMIT)

        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": batch_limit,
        }

        if end_time is not None:
            params["endTime"] = end_time

        response = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
        response.raise_for_status()
        rows = response.json()

        if not rows:
            break

        new_rows = []
        for row in rows:
            open_time = row[0]
            if open_time not in seen_open_times:
                seen_open_times.add(open_time)
                new_rows.append(row)

        if not new_rows:
            break

        all_rows.extend(new_rows)

        oldest_open_time = new_rows[0][0]
        end_time = oldest_open_time - 1

        if len(rows) < batch_limit:
            break

    if not all_rows:
        raise ValueError("No kline data returned from Binance.")

    all_rows = sorted(all_rows, key=lambda x: x[0])[-limit:]

    columns = [
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

    df = pd.DataFrame(all_rows, columns=columns)

    numeric_cols = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
        "taker_buy_base_asset_volume",
        "taker_buy_quote_asset_volume",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    int_cols = ["number_of_trades"]
    for col in int_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

    return df.reset_index(drop=True)
