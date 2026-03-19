from dotenv import load_dotenv
load_dotenv()

print("bot.main started")

from bot.execution.roostoo_client import RoostooClient
from bot.logs.trade_logger import TradeLogger
from bot.logs.activity_logger import setup_activity_logger
from bot.data.binance_loader import load_binance_klines
from bot.strategy.vwap_reversion import generate_vwap_signal
from bot.config import settings


client = RoostooClient()
trade_logger = TradeLogger()
activity_logger = setup_activity_logger()


def run_once():
    print("Entered run_once")

    symbol = getattr(settings, "BINANCE_SYMBOL", "BTCUSDT")
    pair = getattr(settings, "ROOSTOO_PAIR", getattr(settings, "SYMBOL", "BTC/USD"))
    interval = settings.INTERVAL
    limit = settings.LIMIT
    vwap_window = settings.VWAP_WINDOW
    qty = 0.01
    base_coin = "BTC"

    try:
        print("Loading Binance data...")
        df = load_binance_klines(symbol=symbol, interval=interval, limit=limit)

        print("Generating signal...")
        df = generate_vwap_signal(df, window=vwap_window)

        print("Rows in df:", len(df))

        if len(df) < 2:
            print("Not enough rows to evaluate signal.")
            return

        required_cols = ["close", "vwap", "upper_band", "lower_band", "signal"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            print("Missing required columns:", missing_cols)
            return

        if df[required_cols].tail(2).isnull().any().any():
            print("Latest rows contain NaN values. Skipping run.")
            return

        print("\nLatest rows:")
        print(df[required_cols].tail(5))

        prev_row = df.iloc[-2]
        latest_row = df.iloc[-1]

        prev_signal = int(prev_row["signal"])
        latest_signal = int(latest_row["signal"])

        print("\nprev_signal =", prev_signal)
        print("latest_signal =", latest_signal)

        if prev_signal not in (0, 1) or latest_signal not in (0, 1):
            print("This main.py assumes long-only signals: 0 = flat, 1 = long.")
            print("Unexpected signal values detected.")
            return

        side = None
        signal_reason = None

        if prev_signal == 0 and latest_signal == 1:
            side = "BUY"
            signal_reason = "Signal flipped from 0 to 1"

        elif prev_signal == 1 and latest_signal == 0:
            btc_free = client.get_free_balance(base_coin)
            print(f"Free {base_coin} balance:", btc_free)

            if btc_free < qty:
                print(f"Skip SELL: only {btc_free} {base_coin} available, need {qty}")
                return

            side = "SELL"
            signal_reason = "Signal flipped from 1 to 0"

        if side is None:
            print("No trade signal.")
            return

        print(f"\nPlacing {side} order...")
        order_response = client.place_order(
            pair=pair,
            side=side,
            quantity=qty,
            order_type="MARKET",
        )

        print("Order response:")
        print(order_response)

        order_id = order_response.get("OrderDetail", {}).get("OrderID", "")

        if order_id:
            print("\nOrder query by ID:")
            print(client.query_order(order_id=order_id))
        else:
            print("\nOrder ID not found in response. Falling back to pair query:")
            print(client.query_order(pair=pair, limit=5))

        print("\nUpdated balance:")
        print(client.get_balance())

        try:
            trade_logger.log_trade(
                symbol=symbol,
                side=side,
                price=float(latest_row["close"]),
                quantity=qty,
                order_id=str(order_id),
                api_response=order_response,
                pnl=None,
                signal_reason=signal_reason,
                strategy_state={
                    "pair": pair,
                    "prev_signal": prev_signal,
                    "latest_signal": latest_signal,
                    "vwap": float(latest_row["vwap"]),
                    "upper_band": float(latest_row["upper_band"]),
                    "lower_band": float(latest_row["lower_band"]),
                },
            )
        except Exception as log_error:
            print("Trade log failed:", log_error)

        try:
            activity_logger.info(
                f"Placed {side} order for {qty} {pair}. Reason: {signal_reason}"
            )
        except Exception as log_error:
            print("Activity log failed:", log_error)

    except Exception as e:
        print("run_once failed:", e)
        try:
            activity_logger.exception("run_once failed")
        except Exception:
            pass


if __name__ == "__main__":
    print("Starting bot...")
    run_once()
    print("Bot finished.")
