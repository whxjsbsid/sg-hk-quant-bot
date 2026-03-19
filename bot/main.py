from dotenv import load_dotenv
load_dotenv()

print("bot.main started")

from bot.execution.roostoo_client import RoostooClient
from bot.logs.trade_logger import TradeLogger
from bot.logs.activity_logger import setup_activity_logger
from bot.data.binance_loader import load_binance_klines
from bot.strategy.vwap_reversion import generate_vwap_signal


client = RoostooClient()
trade_logger = TradeLogger()
activity_logger = setup_activity_logger()


def run_once():
    print("Entered run_once")

    symbol = "BTCUSDT"
    pair = "BTC/USD"
    interval = "1d"
    limit = 300
    qty = 0.01

    try:
        print("Loading Binance data...")
        df = load_binance_klines(symbol=symbol, interval=interval, limit=limit)

        print("Generating signal...")
        df = generate_vwap_signal(df, window=20)

        print("Rows in df:", len(df))

        if len(df) < 2:
            print("Not enough rows to evaluate signal.")
            return

        prev_row = df.iloc[-2]
        latest_row = df.iloc[-1]

        prev_signal = int(prev_row["signal"])
        latest_signal = int(latest_row["signal"])

        print("prev_signal =", prev_signal)
        print("latest_signal =", latest_signal)

        side = None
        signal_reason = None

        if prev_signal == 0 and latest_signal == 1:
            side = "BUY"
            signal_reason = "Signal flipped from 0 to 1"
        elif prev_signal == 1 and latest_signal == 0:
            side = "SELL"
            signal_reason = "Signal flipped from 1 to 0"

        if side is None:
            print("No trade signal.")
            return

        print(f"Placing {side} order...")
        order_response = client.place_order(
            pair=pair,
            side=side,
            quantity=qty,
            order_type="MARKET",
        )

        print("Order response:", order_response)

    except Exception as e:
        print("run_once failed:", e)


if __name__ == "__main__":
    print("Starting bot...")
    run_once()
    print("Bot finished.")
