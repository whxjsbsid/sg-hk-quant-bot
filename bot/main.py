from bot.execution.roostoo_client import RoostooClient
from bot.logs.trade_logger import TradeLogger
from bot.logs.activity_logger import setup_activity_logger
from bot.data.binance_loader import load_binance_klines
from bot.strategy.vwap_reversion import generate_vwap_signal
import pandas as pd


client = RoostooClient()
trade_logger = TradeLogger()
activity_logger = setup_activity_logger()


def run_once():
    symbol = "BTCUSDT"
    pair = "BTC/USD"
    interval = "1d"
    limit = 300
    qty = 0.01

    try:
        df = load_binance_klines(symbol=symbol, interval=interval, limit=limit)
        df = generate_vwap_signal(df, window=20)

        closed_df = df.iloc[:-1].copy()

        if len(closed_df) < 2:
            activity_logger.info("Not enough closed rows to evaluate signal.")
            return

        prev_row = closed_df.iloc[-2]
        latest_row = closed_df.iloc[-1]

        if pd.isna(prev_row["signal"]) or pd.isna(latest_row["signal"]):
            activity_logger.info("Signal not ready yet.")
            return

        prev_signal = int(prev_row["signal"])
        latest_signal = int(latest_row["signal"])

        side = None
        signal_reason = None

        if prev_signal == 0 and latest_signal == 1:
            side = "BUY"
            signal_reason = "Entry: close < lower_band"
        elif prev_signal == 1 and latest_signal == 0:
            side = "SELL"
            signal_reason = "Exit condition met"

        if side is None:
            activity_logger.info(
                f"No new trade. prev_signal={prev_signal}, latest_signal={latest_signal}"
            )
            return

        strategy_state = {
            "close": float(latest_row["close"]),
            "vwap": float(latest_row["vwap"]),
            "std": float(latest_row["std"]),
            "lower_band": float(latest_row["lower_band"]),
            "strong_upper_band": float(latest_row["strong_upper_band"]),
            "signal": latest_signal,
        }

        order_response = client.place_order(
            pair=pair,
            side=side,
            order_type="MARKET",
            quantity=qty,
        )

        activity_logger.info(f"Raw order response: {order_response}")

        order_id = str(order_response.get("order_id", ""))
        executed_price = float(order_response.get("price", latest_row["close"]))
        executed_qty = float(order_response.get("quantity", qty))

        trade_logger.log_trade(
            symbol=pair,
            side=side,
            price=executed_price,
            quantity=executed_qty,
            order_id=order_id,
            api_response=order_response,
            signal_reason=signal_reason,
            strategy_state=strategy_state,
        )

        activity_logger.info(
            f"Logged {side} trade for {pair} | order_id={order_id}"
        )

    except Exception as e:
        activity_logger.exception(f"Trade failed: {e}")


if __name__ == "__main__":
    run_once()
