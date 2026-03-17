import pandas as pd

# =========================
# SETTINGS
# =========================
CSV_FILE = "data/BTCUSDT_1d.csv"

LOOKBACK = 20
ENTRY_Z = -1.5          # buy when z-score is below this
EXIT_Z = -0.2           # sell when z-score recovers above this
STARTING_CASH = 10000.0
FEE_RATE = 0.001        # example 0.1% per trade
POSITION_SIZE = 1.0     # use 100% of available cash each time


# =========================
# LOAD DATA
# =========================
def load_binance_csv(file_path: str) -> pd.DataFrame:
    df = pd.read_csv(file_path, header=None)

    df.columns = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ]

    # keep only what we need
    df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()

    # convert types
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df


# =========================
# SIGNAL LOGIC
# =========================
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["ma"] = df["close"].rolling(LOOKBACK).mean()
    df["std"] = df["close"].rolling(LOOKBACK).std()
    df["zscore"] = (df["close"] - df["ma"]) / df["std"]

    return df


# =========================
# BACKTEST
# =========================
def run_backtest(df: pd.DataFrame):
    cash = STARTING_CASH
    units = 0.0
    in_position = False

    trade_log = []

    for i in range(len(df)):
        row = df.iloc[i]

        # skip until enough data for rolling stats
        if pd.isna(row["ma"]) or pd.isna(row["std"]) or row["std"] == 0:
            continue

        date = row["open_time"]
        close_price = row["close"]
        z = row["zscore"]

        # BUY SIGNAL
        if (not in_position) and (z <= ENTRY_Z):
            # how much cash to deploy
            deploy_cash = cash * POSITION_SIZE

            if deploy_cash > 0:
                fee = deploy_cash * FEE_RATE
                net_cash_to_invest = deploy_cash - fee
                bought_units = net_cash_to_invest / close_price

                units += bought_units
                cash -= deploy_cash
                in_position = True

                trade_log.append({
                    "date": date,
                    "action": "BUY",
                    "price": close_price,
                    "zscore": z,
                    "cash_after": cash,
                    "units_after": units,
                    "fee": fee
                })

        # SELL SIGNAL
        elif in_position and (z >= EXIT_Z):
            gross_sale_value = units * close_price
            fee = gross_sale_value * FEE_RATE
            net_sale_value = gross_sale_value - fee

            cash += net_sale_value
            units = 0.0
            in_position = False

            trade_log.append({
                "date": date,
                "action": "SELL",
                "price": close_price,
                "zscore": z,
                "cash_after": cash,
                "units_after": units,
                "fee": fee
            })

    # final portfolio value
    final_close = df.iloc[-1]["close"]
    final_value = cash + (units * final_close)

    return {
        "final_cash": cash,
        "final_units": units,
        "final_close": final_close,
        "final_value": final_value,
        "return_pct": ((final_value / STARTING_CASH) - 1) * 100,
        "trade_log": pd.DataFrame(trade_log)
    }


# =========================
# SUMMARY
# =========================
def print_summary(results):
    print("=" * 50)
    print("BACKTEST RESULTS")
    print("=" * 50)
    print(f"Starting cash: {STARTING_CASH:.2f}")
    print(f"Final portfolio value: {results['final_value']:.2f}")
    print(f"Return: {results['return_pct']:.2f}%")
    print(f"Final cash: {results['final_cash']:.2f}")
    print(f"Final units held: {results['final_units']:.6f}")
    print(f"Last close: {results['final_close']:.2f}")
    print("=" * 50)

    trade_log = results["trade_log"]
    print(f"Number of trades: {len(trade_log)}")

    if not trade_log.empty:
        print("\nLast 10 trades:")
        print(trade_log.tail(10).to_string(index=False))


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    df = load_binance_csv(CSV_FILE)
    df = add_indicators(df)

    results = run_backtest(df)
    print_summary(results)
