from bot.execution.roostoo_client import RoostooClient
from bot.logs.trade_logger import TradeLogger
from bot.logs.activity_logger import setup_activity_logger

client = RoostooClient()
trade_logger = TradeLogger()
activity_logger = setup_activity_logger()

def run_once():
    # example only
    pair = "BTC/USD"
    side = "BUY"
    qty = 0.01

    order_response = client.place_order(
        pair=pair,
        side=side,
        order_type="MARKET",
        quantity=qty,
    )

    order_id = str(order_response.get("order_id", ""))
    executed_price = float(order_response.get("price", 0))
    executed_qty = float(order_response.get("quantity", qty))

    trade_logger.log_trade(
        symbol=pair,
        side=side,
        price=executed_price,
        quantity=executed_qty,
        order_id=order_id,
        api_response=order_response,
        signal_reason="your signal here",
        strategy_state={"strategy": "vwap_reversion"},
    )

    activity_logger.info(f"Logged {side} trade for {pair} | order_id={order_id}")

if __name__ == "__main__":
    run_once()
