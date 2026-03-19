from bot.execution.roostoo_client import RoostooClient
from bot.logs.trade_logger import TradeLogger
from bot.logs.activity_logger import setup_activity_logger


client = RoostooClient()
trade_logger = TradeLogger()
activity_logger = setup_activity_logger()


def run_once():
    pair = "BTC/USD"
    side = "BUY"
    qty = 0.01

    try:
        order_response = client.place_order(
            pair=pair,
            side=side,
            order_type="MARKET",
            quantity=qty,
        )

        if not order_response or not order_response.get("Success"):
            err_msg = order_response.get("ErrMsg", "Unknown error") if order_response else "No response"
            activity_logger.error(f"Trade failed: {err_msg}")
            return

        order_detail = order_response.get("OrderDetail", {})

        order_id = str(order_detail.get("OrderID", ""))
        status = order_detail.get("Status", "")
        executed_price = float(order_detail.get("FilledAverPrice") or order_detail.get("Price") or 0)
        executed_qty = float(order_detail.get("FilledQuantity") or order_detail.get("Quantity") or qty)

        trade_logger.log_trade(
            symbol=pair,
            side=side,
            price=executed_price,
            quantity=executed_qty,
            order_id=order_id,
            api_response=order_response,
            signal_reason="your signal here",
            strategy_state={
                "strategy": "vwap_reversion",
                "status": status,
            },
        )

        activity_logger.info(
            f"Logged {side} trade for {pair} | order_id={order_id} | status={status}"
        )

    except Exception as e:
        activity_logger.exception(f"Trade failed: {e}")


if __name__ == "__main__":
    run_once()


if __name__ == "__main__":
    run_once()
