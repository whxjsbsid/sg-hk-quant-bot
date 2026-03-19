from dotenv import load_dotenv
load_dotenv()

from bot.execution.roostoo_client import RoostooClient
from bot.logs.trade_logger import TradeLogger
from bot.logs.activity_logger import setup_activity_logger
from bot.data.binance_loader import load_binance_klines
from bot.strategy.vwap_reversion import generate_vwap_signal


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

        if len(df) < 2:
            activity_logger.info("Not enough rows to evaluate signal.")
            return

        prev_row = df.iloc[-2]
        latest_row = df.iloc[-1]

        prev_signal = int(prev_row["signal"])
        latest_signal = int(latest_row["signal"])

        side = None
        signal_reason = None

        if prev_signal == 0 and latest_signal == 1:
            side = "BUY"
            signal_reason = "Signal flipped from 0 to 1"
        elif prev_signal == 1 and latest_signal == 0:
            side = "SELL"
            signal_reason = "Signal flipped from 1 to 0"

        if side is None:
            activity_logger.info(
                f"No trade. prev_signal={prev_signal}, latest_signal={latest_signal}"
            )
            return

        order_response = client.place_order(
            pair=pair,
            side=side,
            quantity=qty,
            order_type="MARKET",
        )

        activity_logger.info(
            f"Placed {side} order for {qty} {pair}. Reason: {signal_reason}"
        )

        trade_logger.log_trade({
            "symbol": symbol,
            "pair": pair,
            "side": side,
            "qty": qty,
            "reason": signal_reason,
            "prev_signal": prev_signal,
            "latest_signal": latest_signal,
            "close": float(latest_row["close"]),
            "vwap": float(latest_row["vwap"]),
            "upper_band": float(latest_row.get("upper_band", 0)),
            "lower_band": float(latest_row.get("lower_band", 0)),
            "order_response": order_response,
        })

    except Exception as e:
        activity_logger.exception(f"run_once failed: {e}")


if __name__ == "__main__":
    run_once()
