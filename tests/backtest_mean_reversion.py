import pandas as pd

CSV_FILE = "data/BTCUSDT-1d-2024-01.csv"
LOOKBACK = 20
ENTRY_Z = -1.5
EXIT_Z = -0.2
STARTING_CASH = 10000.0
FEE_RATE = 0.001

df = pd.read_csv(CSV_FILE, header=None)
df.columns = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "number_of_trades",
    "taker_buy_base", "taker_buy_quote", "ignore"
]

df["close"] = df["close"].astype(float)
df["ma"] = df["close"].rolling(LOOKBACK).mean()
df["std"] = df["close"].rolling(LOOKBACK).std()
df["zscore"] = (df["close"] - df["ma"]) / df["std"]

cash = STARTING_CASH
btc = 0.0
in_position = False

for _, row in df.iterrows():
    if pd.isna(row["zscore"]) or row["std"] == 0:
        continue

    price = row["close"]
    z = row["zscore"]

    if (not in_position) and (z <= ENTRY_Z):
        fee = cash * FEE_RATE
        btc = (cash - fee) / price
        cash = 0.0
        in_position = True
        print(f"BUY at {price:.2f}, z={z:.2f}")

    elif in_position and (z >= EXIT_Z):
        sale_value = btc * price
        fee = sale_value * FEE_RATE
        cash = sale_value - fee
        btc = 0.0
        in_position = False
        print(f"SELL at {price:.2f}, z={z:.2f}")

final_price = df.iloc[-1]["close"]
final_value = cash + btc * final_price

print("\n========== RESULT ==========")
print(f"Final portfolio value: {final_value:.2f}")
print(f"Return: {((final_value / STARTING_CASH) - 1) * 100:.2f}%")
